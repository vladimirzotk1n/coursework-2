"""
Запуск: docker compose run --rm backend python scripts/capture_series.py
"""
import asyncio
import json
import base64

from httpx import ASGITransport, AsyncClient


def hr(label):
    print(f"\n{'─'*64}\n# {label}")

def show_req(method, path, body=None):
    print(f"\n{method} {path}")
    if body:
        print(json.dumps(body, ensure_ascii=False, indent=2))

def show_resp(r):
    print(f"\nHTTP {r.status_code}")
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(r.text[:200])

async def register_and_login(client, username, email, password="secret123"):
    await client.post("/auth/register", json={"username": username, "email": email, "password": password})
    r = await client.post("/auth/login", data={"username": username, "password": password})
    return r.json()["access_token"]

def auth(token):
    return {"Authorization": f"Bearer {token}"}

async def setup_run(client, token):
    exp_id = (await client.post("/experiments", json={"title": "Exp"}, headers=auth(token))).json()["experiment_id"]
    run_id = (await client.post(f"/experiments/{exp_id}/runs", json={"name": "Run"}, headers=auth(token))).json()["run_id"]
    return run_id

async def main():
    from app.core import db as db_module
    from app.core.db import apply_schema, close_pool, get_pool
    from app.main import app as fastapi_app
    from app.storage import s3 as s3_module
    from app.storage.s3 import ensure_bucket

    db_module._pool = None
    s3_module._session = None
    await apply_schema()
    await ensure_bucket()
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cser_%'")

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        token = await register_and_login(client, "_cser_alice", "_cser_alice@test.com")

        # ── 1. Создание серии ────────────────────────────────────────────────
        hr("1. Создание серии данных")
        run_id = await setup_run(client, token)
        body = {"series_name": "Напряжение", "unit_x": "t, с", "unit_y": "U, В"}
        show_req("POST", f"/runs/{run_id}/series", body)
        r1 = await client.post(f"/runs/{run_id}/series", json=body, headers=auth(token))
        show_resp(r1)
        series_id = r1.json()["series_id"]

        # ── 2. Добавление точек и сортировка по measurement_order ────────────
        hr("2. Точки добавляются в произвольном порядке, возвращаются отсортированными")
        run_id2 = await setup_run(client, token)
        s2 = (await client.post(f"/runs/{run_id2}/series", json={"series_name": "S"}, headers=auth(token))).json()["series_id"]

        for order in [3, 1, 2]:
            p = {"measurement_order": order, "x_value": float(order), "y_value": float(order) * 0.5}
            r = await client.post(f"/series/{s2}/points", json=p, headers=auth(token))
            print(f"  POST /series/{s2}/points  measurement_order={order}  →  HTTP {r.status_code}")

        show_req("GET", f"/series/{s2}/points")
        rp = await client.get(f"/series/{s2}/points", headers=auth(token))
        show_resp(rp)

        # ── 3. Дублирование measurement_order отклоняется ────────────────────
        hr("3. PUT с дублирующимися measurement_order отклоняется (код 422)")
        run_id3 = await setup_run(client, token)
        s3 = (await client.post(f"/runs/{run_id3}/series", json={"series_name": "Dup"}, headers=auth(token))).json()["series_id"]
        dup_body = {"points": [
            {"measurement_order": 1, "x_value": 0.0, "y_value": 0.0},
            {"measurement_order": 1, "x_value": 1.0, "y_value": 1.0},
        ]}
        show_req("PUT", f"/series/{s3}/points", dup_body)
        r3 = await client.put(f"/series/{s3}/points", json=dup_body, headers=auth(token))
        show_resp(r3)

        # ── 4. Каскадное удаление серии → точки ─────────────────────────────
        hr("4. Удаление серии — каскадное удаление DataPoints")
        run_id4 = await setup_run(client, token)
        s4 = (await client.post(f"/runs/{run_id4}/series", json={"series_name": "ToDelete"}, headers=auth(token))).json()["series_id"]
        for i in range(1, 4):
            await client.post(f"/series/{s4}/points",
                json={"measurement_order": i, "x_value": float(i), "y_value": 0.0},
                headers=auth(token))

        async with pool.acquire() as conn:
            count_before = await conn.fetchval('SELECT COUNT(*) FROM "DataPoints" WHERE series_id = $1', s4)
        print(f'\n-- SELECT COUNT(*) FROM "DataPoints" WHERE series_id = {s4};  -- {count_before}')

        show_req("DELETE", f"/series/{s4}")
        rd = await client.delete(f"/series/{s4}", headers=auth(token))
        show_resp(rd)

        async with pool.acquire() as conn:
            count_after = await conn.fetchval('SELECT COUNT(*) FROM "DataPoints" WHERE series_id = $1', s4)
        print(f'-- SELECT COUNT(*) FROM "DataPoints" WHERE series_id = {s4};  -- {count_after}')

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cser_%'")
    await close_pool()
    print("\n" + "="*64 + "\nГотово.")

asyncio.run(main())
