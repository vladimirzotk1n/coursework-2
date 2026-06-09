"""
Запуск: docker compose run --rm backend python scripts/capture_runs.py
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
    token = r.json()["access_token"]
    payload_b64 = token.split(".")[1] + "=="
    payload = json.loads(base64.b64decode(payload_b64))
    return token, int(payload["sub"])

def auth(token):
    return {"Authorization": f"Bearer {token}"}

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
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_crun_%'")

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        t1, uid1 = await register_and_login(client, "_crun_alice", "_crun_alice@test.com")
        t2, _    = await register_and_login(client, "_crun_bob",   "_crun_bob@test.com")

        # создаём эксперимент
        exp_id = (await client.post("/experiments", json={"title": "Exp"}, headers=auth(t1))).json()["experiment_id"]

        # ── 1. Первый запуск → run_number = 1 ───────────────────────────────
        hr("1. Создание первого запуска — run_number присваивается триггером")
        body = {"name": "Запуск 1"}
        show_req("POST", f"/experiments/{exp_id}/runs", body)
        r1 = await client.post(f"/experiments/{exp_id}/runs", json=body, headers=auth(t1))
        show_resp(r1)

        # ── 2. Последовательная нумерация ────────────────────────────────────
        hr("2. Последовательное создание трёх запусков — run_number 1, 2, 3")
        exp2_id = (await client.post("/experiments", json={"title": "Exp2"}, headers=auth(t1))).json()["experiment_id"]
        for i in range(1, 4):
            r = await client.post(f"/experiments/{exp2_id}/runs", json={"name": f"Запуск {i}"}, headers=auth(t1))
            print(f"  POST /experiments/{exp2_id}/runs  →  HTTP {r.status_code}  run_number={r.json()['run_number']}")

        # ── 3. Независимость счётчиков ───────────────────────────────────────
        hr("3. Независимость run_number между экспериментами")
        exp_a = (await client.post("/experiments", json={"title": "A"}, headers=auth(t1))).json()["experiment_id"]
        exp_b = (await client.post("/experiments", json={"title": "B"}, headers=auth(t1))).json()["experiment_id"]
        ra = await client.post(f"/experiments/{exp_a}/runs", json={"name": "Run"}, headers=auth(t1))
        rb = await client.post(f"/experiments/{exp_b}/runs", json={"name": "Run"}, headers=auth(t1))
        print(f"  POST /experiments/{exp_a}/runs  →  run_number={ra.json()['run_number']}")
        print(f"  POST /experiments/{exp_b}/runs  →  run_number={rb.json()['run_number']}")

        # ── 4. Конкурентный доступ ───────────────────────────────────────────
        hr("4. Конкурентное создание 8 запусков в одном эксперименте")
        exp_c = (await client.post("/experiments", json={"title": "Concurrent"}, headers=auth(t1))).json()["experiment_id"]
        print(f"\n  8 одновременных POST /experiments/{exp_c}/runs ...")
        responses = await asyncio.gather(*[
            client.post(f"/experiments/{exp_c}/runs", json={"name": f"Run {i}"}, headers=auth(t1))
            for i in range(8)
        ])
        statuses = [r.status_code for r in responses]
        numbers  = sorted(r.json()["run_number"] for r in responses)
        print(f"  HTTP статусы:  {statuses}")
        print(f"  run_number (отсортированные): {numbers}")

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT run_number FROM "ExperimentRuns" WHERE experiment_id = $1 ORDER BY run_number',
                exp_c
            )
        print(f"\n-- SELECT run_number FROM \"ExperimentRuns\" WHERE experiment_id = {exp_c};")
        print(f"  run_number: {[r['run_number'] for r in rows]}")

        # ── 5. Изоляция: чужой запуск недоступен ────────────────────────────
        hr("5. Попытка доступа к запуску другого пользователя")
        run_id = r1.json()["run_id"]
        show_req("GET", f"/runs/{run_id}  (токен bob)")
        r5 = await client.get(f"/runs/{run_id}", headers=auth(t2))
        show_resp(r5)

        # ── 6. Удаление запуска ──────────────────────────────────────────────
        hr("6. Удаление запуска")
        del_run_id = (await client.post(f"/experiments/{exp_id}/runs", json={"name": "Удалить"}, headers=auth(t1))).json()["run_id"]
        show_req("DELETE", f"/runs/{del_run_id}")
        rd = await client.delete(f"/runs/{del_run_id}", headers=auth(t1))
        show_resp(rd)
        show_req("GET", f"/runs/{del_run_id}  (после удаления)")
        show_resp(await client.get(f"/runs/{del_run_id}", headers=auth(t1)))

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_crun_%'")
    await close_pool()
    print("\n" + "="*64 + "\nГотово.")

asyncio.run(main())
