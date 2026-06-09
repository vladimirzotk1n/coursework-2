"""
Группа 3: Создание, изменение и удаление запусков эксперимента.
Группа 4: Работа триггера trg_run_number; изоляция данных между пользователями.
"""
import asyncio

from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_login


async def _make_experiment(client: AsyncClient, token: str, title: str = "Exp") -> int:
    r = await client.post("/experiments", json={"title": title}, headers=auth_headers(token))
    assert r.status_code == 201
    return r.json()["experiment_id"]


async def test_create_run_assigns_run_number_1(client: AsyncClient):
    token = await register_and_login(client, "0r1", "0r1@test.com")
    exp_id = await _make_experiment(client, token)

    r = await client.post(
        f"/experiments/{exp_id}/runs",
        json={"name": "First Run"},
        headers=auth_headers(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["run_number"] == 1
    assert body["name"] == "First Run"
    assert body["experiment_id"] == exp_id


async def test_sequential_run_numbers(client: AsyncClient):
    """trg_run_number присваивает номера 1, 2, 3 по порядку."""
    token = await register_and_login(client, "0r2", "0r2@test.com")
    exp_id = await _make_experiment(client, token)

    for expected in range(1, 4):
        r = await client.post(
            f"/experiments/{exp_id}/runs",
            json={"name": f"Run {expected}"},
            headers=auth_headers(token),
        )
        assert r.json()["run_number"] == expected


async def test_run_numbers_are_independent_per_experiment(client: AsyncClient):
    """Каждый эксперимент имеет свою последовательность run_number, начинающуюся с 1."""
    token = await register_and_login(client, "0r3", "0r3@test.com")
    exp1 = await _make_experiment(client, token, "Exp A")
    exp2 = await _make_experiment(client, token, "Exp B")

    r1 = await client.post(
        f"/experiments/{exp1}/runs", json={"name": "Run"}, headers=auth_headers(token)
    )
    r2 = await client.post(
        f"/experiments/{exp2}/runs", json={"name": "Run"}, headers=auth_headers(token)
    )
    assert r1.json()["run_number"] == 1
    assert r2.json()["run_number"] == 1


async def test_concurrent_run_numbers_are_unique_and_sequential(client: AsyncClient):
    """
    pg_advisory_xact_lock в fn_assign_run_number сериализует конкурентные INSERT'ы
    для одного эксперимента, поэтому все run_number должны быть уникальны
    и образовывать непрерывную последовательность 1..N.
    """
    token = await register_and_login(client, "0r4", "0r4@test.com")
    exp_id = await _make_experiment(client, token)

    N = 8
    responses = await asyncio.gather(
        *[
            client.post(
                f"/experiments/{exp_id}/runs",
                json={"name": f"Concurrent {i}"},
                headers=auth_headers(token),
            )
            for i in range(N)
        ]
    )

    assert all(r.status_code == 201 for r in responses)
    numbers = sorted(r.json()["run_number"] for r in responses)
    assert numbers == list(range(1, N + 1))


async def test_list_runs_ordered_by_run_number(client: AsyncClient):
    token = await register_and_login(client, "0r5", "0r5@test.com")
    exp_id = await _make_experiment(client, token)

    for i in range(3):
        await client.post(
            f"/experiments/{exp_id}/runs",
            json={"name": f"Run {i}"},
            headers=auth_headers(token),
        )

    r = await client.get(f"/experiments/{exp_id}/runs", headers=auth_headers(token))
    assert r.status_code == 200
    nums = [row["run_number"] for row in r.json()]
    assert nums == sorted(nums)


async def test_update_run(client: AsyncClient):
    token = await register_and_login(client, "0r6", "0r6@test.com")
    exp_id = await _make_experiment(client, token)
    run_id = (
        await client.post(
            f"/experiments/{exp_id}/runs", json={"name": "Old"}, headers=auth_headers(token)
        )
    ).json()["run_id"]

    r = await client.patch(
        f"/runs/{run_id}",
        json={"name": "New", "description": "Changed"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New"
    assert r.json()["description"] == "Changed"


async def test_update_run_triggers_updated_at(client: AsyncClient):
    token = await register_and_login(client, "0r7", "0r7@test.com")
    exp_id = await _make_experiment(client, token)
    create_r = await client.post(
        f"/experiments/{exp_id}/runs", json={"name": "Trigger"}, headers=auth_headers(token)
    )
    run_id = create_r.json()["run_id"]
    original = create_r.json()["updated_at"]

    patch_r = await client.patch(
        f"/runs/{run_id}", json={"name": "Trigger Updated"}, headers=auth_headers(token)
    )
    assert patch_r.json()["updated_at"] >= original


async def test_delete_run(client: AsyncClient):
    token = await register_and_login(client, "0r8", "0r8@test.com")
    exp_id = await _make_experiment(client, token)
    run_id = (
        await client.post(
            f"/experiments/{exp_id}/runs", json={"name": "Delete me"}, headers=auth_headers(token)
        )
    ).json()["run_id"]

    assert (await client.delete(f"/runs/{run_id}", headers=auth_headers(token))).status_code == 204
    assert (await client.get(f"/runs/{run_id}", headers=auth_headers(token))).status_code == 404


async def test_access_other_users_run_returns_404(client: AsyncClient):
    t1 = await register_and_login(client, "0r9", "0r9@test.com")
    t2 = await register_and_login(client, "r10", "r10@test.com")
    exp_id = await _make_experiment(client, t1)
    run_id = (
        await client.post(
            f"/experiments/{exp_id}/runs", json={"name": "Private"}, headers=auth_headers(t1)
        )
    ).json()["run_id"]

    r = await client.get(f"/runs/{run_id}", headers=auth_headers(t2))
    assert r.status_code == 404
