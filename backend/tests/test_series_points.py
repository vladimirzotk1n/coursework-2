"""
Группа 3: Создание и удаление серий данных и точек измерений.
Группа 4: Изоляция серий по пользователю.
Группа 5: Каскадное удаление DataPoints при удалении DataSeries.
"""
from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_login


async def _setup_run(client: AsyncClient, username: str, email: str) -> tuple[str, int]:
    """Регистрирует пользователя, создаёт эксперимент и запуск, возвращает (token, run_id)."""
    token = await register_and_login(client, username, email)
    exp_id = (
        await client.post("/experiments", json={"title": "Exp"}, headers=auth_headers(token))
    ).json()["experiment_id"]
    run_id = (
        await client.post(
            f"/experiments/{exp_id}/runs", json={"name": "Run"}, headers=auth_headers(token)
        )
    ).json()["run_id"]
    return token, run_id


async def test_create_series(client: AsyncClient):
    token, run_id = await _setup_run(client, "0s1", "0s1@test.com")
    r = await client.post(
        f"/runs/{run_id}/series",
        json={"series_name": "Voltage", "unit_x": "t, s", "unit_y": "U, V"},
        headers=auth_headers(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["series_name"] == "Voltage"
    assert body["unit_x"] == "t, s"
    assert body["unit_y"] == "U, V"
    assert body["run_id"] == run_id


async def test_add_and_list_points(client: AsyncClient):
    token, run_id = await _setup_run(client, "0s2", "0s2@test.com")
    series_id = (
        await client.post(
            f"/runs/{run_id}/series", json={"series_name": "Current"}, headers=auth_headers(token)
        )
    ).json()["series_id"]

    point = {
        "measurement_order": 1,
        "x_value": 0.5,
        "y_value": 1.5,
        "x_uncertainty": 0.01,
        "y_uncertainty": 0.05,
    }
    r = await client.post(f"/series/{series_id}/points", json=point, headers=auth_headers(token))
    assert r.status_code == 201
    assert r.json()["y_value"] == 1.5

    r = await client.get(f"/series/{series_id}/points", headers=auth_headers(token))
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["measurement_order"] == 1


async def test_points_ordered_by_measurement_order(client: AsyncClient):
    token, run_id = await _setup_run(client, "0s3", "0s3@test.com")
    series_id = (
        await client.post(
            f"/runs/{run_id}/series", json={"series_name": "Ordered"}, headers=auth_headers(token)
        )
    ).json()["series_id"]

    for order in [3, 1, 2]:
        await client.post(
            f"/series/{series_id}/points",
            json={"measurement_order": order, "x_value": float(order), "y_value": 0.0},
            headers=auth_headers(token),
        )

    r = await client.get(f"/series/{series_id}/points", headers=auth_headers(token))
    orders = [p["measurement_order"] for p in r.json()]
    assert orders == sorted(orders)


async def test_replace_points_replaces_all(client: AsyncClient):
    token, run_id = await _setup_run(client, "0s4", "0s4@test.com")
    series_id = (
        await client.post(
            f"/runs/{run_id}/series", json={"series_name": "Replace"}, headers=auth_headers(token)
        )
    ).json()["series_id"]

    await client.post(
        f"/series/{series_id}/points",
        json={"measurement_order": 1, "x_value": 0.0, "y_value": 0.0},
        headers=auth_headers(token),
    )

    new_points = {
        "points": [
            {"measurement_order": 1, "x_value": 1.0, "y_value": 2.0},
            {"measurement_order": 2, "x_value": 3.0, "y_value": 6.0},
        ]
    }
    r = await client.put(
        f"/series/{series_id}/points", json=new_points, headers=auth_headers(token)
    )
    assert r.status_code == 200
    assert len(r.json()) == 2
    assert r.json()[0]["x_value"] == 1.0
    assert r.json()[1]["x_value"] == 3.0


async def test_replace_points_duplicate_order_rejected(client: AsyncClient):
    """PUT /series/{id}/points проверяет уникальность measurement_order."""
    token, run_id = await _setup_run(client, "0s5", "0s5@test.com")
    series_id = (
        await client.post(
            f"/runs/{run_id}/series", json={"series_name": "DupOrder"}, headers=auth_headers(token)
        )
    ).json()["series_id"]

    r = await client.put(
        f"/series/{series_id}/points",
        json={
            "points": [
                {"measurement_order": 1, "x_value": 0.0, "y_value": 0.0},
                {"measurement_order": 1, "x_value": 1.0, "y_value": 1.0},
            ]
        },
        headers=auth_headers(token),
    )
    assert r.status_code == 422


async def test_update_series(client: AsyncClient):
    token, run_id = await _setup_run(client, "0s6", "0s6@test.com")
    series_id = (
        await client.post(
            f"/runs/{run_id}/series", json={"series_name": "Old Name"}, headers=auth_headers(token)
        )
    ).json()["series_id"]

    r = await client.patch(
        f"/series/{series_id}",
        json={"series_name": "New Name", "unit_x": "x", "unit_y": "y"},
        headers=auth_headers(token),
    )
    assert r.status_code == 200
    assert r.json()["series_name"] == "New Name"


async def test_delete_series_cascades_to_points(client: AsyncClient, db_pool):
    """DataPoints должны удаляться при удалении DataSeries (ON DELETE CASCADE)."""
    token, run_id = await _setup_run(client, "0s7", "0s7@test.com")
    series_id = (
        await client.post(
            f"/runs/{run_id}/series", json={"series_name": "ToDelete"}, headers=auth_headers(token)
        )
    ).json()["series_id"]

    await client.post(
        f"/series/{series_id}/points",
        json={"measurement_order": 1, "x_value": 0.0, "y_value": 0.0},
        headers=auth_headers(token),
    )

    await client.delete(f"/series/{series_id}", headers=auth_headers(token))

    # Серия удалена через API
    r = await client.get(f"/series/{series_id}", headers=auth_headers(token))
    assert r.status_code == 404

    # Точки удалены в БД
    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            'SELECT COUNT(*) FROM "DataPoints" WHERE series_id = $1', series_id
        )
    assert count == 0


async def test_access_other_users_series_returns_404(client: AsyncClient):
    t1, run_id = await _setup_run(client, "0s8", "0s8@test.com")
    t2 = await register_and_login(client, "0s9", "0s9@test.com")

    series_id = (
        await client.post(
            f"/runs/{run_id}/series",
            json={"series_name": "Private"},
            headers=auth_headers(t1),
        )
    ).json()["series_id"]

    r = await client.get(f"/series/{series_id}", headers=auth_headers(t2))
    assert r.status_code == 404
