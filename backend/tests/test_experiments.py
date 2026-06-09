"""
Группа 3: Создание, изменение и удаление экспериментов.
Группа 4: Проверка доступа только к собственным данным; работа триггеров PostgreSQL.
Группа 5: Корректность каскадного удаления связанных сущностей.
"""
from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_login


async def test_create_experiment(client: AsyncClient):
    token = await register_and_login(client, "0u1", "0u1@test.com")
    r = await client.post(
        "/experiments",
        json={"title": "Ohm's Law", "description": "Linear I(U)"},
        headers=auth_headers(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Ohm's Law"
    assert body["description"] == "Linear I(U)"
    assert "experiment_id" in body
    assert "created_at" in body
    assert "updated_at" in body


async def test_list_experiments_empty(client: AsyncClient):
    token = await register_and_login(client, "0u2", "0u2@test.com")
    r = await client.get("/experiments", headers=auth_headers(token))
    assert r.status_code == 200
    assert r.json() == []


async def test_list_experiments_returns_own_only(client: AsyncClient):
    t1 = await register_and_login(client, "0u3", "0u3@test.com")
    t2 = await register_and_login(client, "0u4", "0u4@test.com")

    await client.post("/experiments", json={"title": "A"}, headers=auth_headers(t1))
    await client.post("/experiments", json={"title": "B"}, headers=auth_headers(t2))

    r1 = await client.get("/experiments", headers=auth_headers(t1))
    r2 = await client.get("/experiments", headers=auth_headers(t2))

    assert len(r1.json()) == 1 and r1.json()[0]["title"] == "A"
    assert len(r2.json()) == 1 and r2.json()[0]["title"] == "B"


async def test_get_experiment(client: AsyncClient):
    token = await register_and_login(client, "0u5", "0u5@test.com")
    create_r = await client.post(
        "/experiments", json={"title": "Get test"}, headers=auth_headers(token)
    )
    exp_id = create_r.json()["experiment_id"]

    r = await client.get(f"/experiments/{exp_id}", headers=auth_headers(token))
    assert r.status_code == 200
    assert r.json()["experiment_id"] == exp_id


async def test_get_nonexistent_experiment_returns_404(client: AsyncClient):
    token = await register_and_login(client, "0u6", "0u6@test.com")
    r = await client.get("/experiments/99999", headers=auth_headers(token))
    assert r.status_code == 404


async def test_get_other_users_experiment_returns_404(client: AsyncClient):
    """Пользователь B не должен иметь доступа к эксперименту пользователя A."""
    t1 = await register_and_login(client, "0u7", "0u7@test.com")
    t2 = await register_and_login(client, "0u8", "0u8@test.com")

    exp_id = (
        await client.post("/experiments", json={"title": "Private"}, headers=auth_headers(t1))
    ).json()["experiment_id"]

    r = await client.get(f"/experiments/{exp_id}", headers=auth_headers(t2))
    assert r.status_code == 404


async def test_update_experiment(client: AsyncClient):
    token = await register_and_login(client, "0u9", "0u9@test.com")
    exp_id = (
        await client.post("/experiments", json={"title": "Old"}, headers=auth_headers(token))
    ).json()["experiment_id"]

    r = await client.patch(
        f"/experiments/{exp_id}",
        json={"title": "New", "description": "Updated"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200
    assert r.json()["title"] == "New"
    assert r.json()["description"] == "Updated"


async def test_update_experiment_triggers_updated_at(client: AsyncClient):
    """trg_updated_at_experiments должен обновлять updated_at при каждом PATCH."""
    token = await register_and_login(client, "u10", "u10@test.com")
    create_r = await client.post(
        "/experiments", json={"title": "Trigger Test"}, headers=auth_headers(token)
    )
    exp_id = create_r.json()["experiment_id"]
    original_updated_at = create_r.json()["updated_at"]

    patch_r = await client.patch(
        f"/experiments/{exp_id}",
        json={"title": "Trigger Test Updated"},
        headers=auth_headers(token),
    )
    assert patch_r.json()["updated_at"] >= original_updated_at


async def test_update_other_users_experiment_returns_404(client: AsyncClient):
    t1 = await register_and_login(client, "u11", "u11@test.com")
    t2 = await register_and_login(client, "u12", "u12@test.com")
    exp_id = (
        await client.post("/experiments", json={"title": "Owner's"}, headers=auth_headers(t1))
    ).json()["experiment_id"]

    r = await client.patch(
        f"/experiments/{exp_id}",
        json={"title": "Hijack"},
        headers=auth_headers(t2),
    )
    assert r.status_code == 404


async def test_delete_experiment(client: AsyncClient):
    token = await register_and_login(client, "u13", "u13@test.com")
    exp_id = (
        await client.post("/experiments", json={"title": "Delete me"}, headers=auth_headers(token))
    ).json()["experiment_id"]

    assert (await client.delete(f"/experiments/{exp_id}", headers=auth_headers(token))).status_code == 204
    assert (await client.get(f"/experiments/{exp_id}", headers=auth_headers(token))).status_code == 404


async def test_delete_experiment_cascades_to_runs_and_series(client: AsyncClient):
    """Каскадное удаление: Experiments → ExperimentRuns → DataSeries → DataPoints."""
    token = await register_and_login(client, "u14", "u14@test.com")
    exp_id = (
        await client.post("/experiments", json={"title": "Cascade"}, headers=auth_headers(token))
    ).json()["experiment_id"]
    run_id = (
        await client.post(
            f"/experiments/{exp_id}/runs", json={"name": "Run"}, headers=auth_headers(token)
        )
    ).json()["run_id"]
    series_id = (
        await client.post(
            f"/runs/{run_id}/series",
            json={"series_name": "S"},
            headers=auth_headers(token),
        )
    ).json()["series_id"]
    await client.post(
        f"/series/{series_id}/points",
        json={"measurement_order": 1, "x_value": 0.0, "y_value": 0.0},
        headers=auth_headers(token),
    )

    await client.delete(f"/experiments/{exp_id}", headers=auth_headers(token))

    assert (await client.get(f"/runs/{run_id}", headers=auth_headers(token))).status_code == 404
    assert (await client.get(f"/series/{series_id}", headers=auth_headers(token))).status_code == 404
