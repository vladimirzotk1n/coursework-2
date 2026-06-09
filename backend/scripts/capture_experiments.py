"""
Скрипт для получения реального вывода тестов управления экспериментами.
Запуск: docker compose run --rm backend python scripts/capture_experiments.py
"""
import asyncio
import json

from httpx import ASGITransport, AsyncClient


def hr(label: str):
    print(f"\n{'─' * 64}")
    print(f"# {label}")


def show_request(method: str, path: str, body=None):
    print(f"\n{method} {path}")
    if body:
        print(json.dumps(body, ensure_ascii=False, indent=2))


def show_response(r):
    print(f"\nHTTP {r.status_code}")
    try:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(r.text[:300])


async def show_experiments(conn, label: str, user_id: int):
    rows = await conn.fetch(
        'SELECT experiment_id, title, description, created_at, updated_at '
        'FROM "Experiments" WHERE user_id = $1 ORDER BY experiment_id',
        user_id,
    )
    print(f"\n-- {label}")
    print(f'SELECT experiment_id, title, created_at, updated_at FROM "Experiments" WHERE user_id = {user_id};')
    if rows:
        for r in rows:
            print(
                f"  experiment_id={r['experiment_id']}  title={r['title']!r}"
                f"  created_at={str(r['created_at'])[:23]}"
                f"  updated_at={str(r['updated_at'])[:23]}"
            )
    else:
        print("  (0 rows)")


async def register_and_login(client, username, email, password="secret123"):
    await client.post(
        "/auth/register", json={"username": username, "email": email, "password": password}
    )
    r = await client.post("/auth/login", data={"username": username, "password": password})
    body = r.json()
    token = body["access_token"]
    # получить user_id
    # декодируем sub из JWT payload (base64, без верификации)
    import base64
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
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
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cap_%'")

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:

        t1, uid1 = await register_and_login(client, "_cap_alice", "_cap_alice@test.com")
        t2, uid2 = await register_and_login(client, "_cap_bob",   "_cap_bob@test.com")

        # ── 1. Создание эксперимента ─────────────────────────────────────────
        hr("1. Создание эксперимента с корректными данными")
        body = {"title": "Закон Ома", "description": "Линейная зависимость I(U)"}
        show_request("POST", "/experiments", body)
        r = await client.post("/experiments", json=body, headers=auth(t1))
        show_response(r)
        exp_id = r.json()["experiment_id"]

        async with pool.acquire() as conn:
            await show_experiments(conn, "Таблица Experiments после создания", uid1)

        # ── 2. Получение существующего эксперимента ──────────────────────────
        hr("2. Получение эксперимента по идентификатору")
        show_request("GET", f"/experiments/{exp_id}")
        r2 = await client.get(f"/experiments/{exp_id}", headers=auth(t1))
        show_response(r2)

        # ── 3. Получение несуществующего эксперимента ────────────────────────
        hr("3. Запрос несуществующего эксперимента")
        show_request("GET", "/experiments/99999")
        r3 = await client.get("/experiments/99999", headers=auth(t1))
        show_response(r3)

        # ── 4. Разграничение доступа — список ────────────────────────────────
        hr("4. Разграничение доступа: каждый пользователь видит только свои эксперименты")
        await client.post("/experiments", json={"title": "Эксперимент Боба"}, headers=auth(t2))

        show_request("GET", "/experiments  (токен alice)")
        r4a = await client.get("/experiments", headers=auth(t1))
        show_response(r4a)

        show_request("GET", "/experiments  (токен bob)")
        r4b = await client.get("/experiments", headers=auth(t2))
        show_response(r4b)

        # ── 5. Попытка получить чужой эксперимент ───────────────────────────
        hr("5. Попытка получить эксперимент другого пользователя")
        show_request("GET", f"/experiments/{exp_id}  (токен bob)")
        r5 = await client.get(f"/experiments/{exp_id}", headers=auth(t2))
        show_response(r5)

        # ── 6. Изменение эксперимента + триггер updated_at ──────────────────
        hr("6. Изменение эксперимента — триггер trg_updated_at_experiments")
        created_at  = r.json()["created_at"]
        updated_at0 = r.json()["updated_at"]
        print(f"\n  updated_at до PATCH: {updated_at0}")

        show_request("PATCH", f"/experiments/{exp_id}", {"title": "Закон Ома (уточнённый)"})
        r6 = await client.patch(
            f"/experiments/{exp_id}",
            json={"title": "Закон Ома (уточнённый)"},
            headers=auth(t1),
        )
        show_response(r6)
        updated_at1 = r6.json()["updated_at"]
        print(f"\n  updated_at после PATCH: {updated_at1}")
        print(f"  updated_at изменился:   {updated_at1 >= updated_at0}")

        async with pool.acquire() as conn:
            await show_experiments(conn, "Таблица Experiments после PATCH", uid1)

        # ── 7. Попытка изменить чужой эксперимент ───────────────────────────
        hr("7. Попытка изменить эксперимент другого пользователя")
        show_request("PATCH", f"/experiments/{exp_id}  (токен bob)", {"title": "Взлом"})
        r7 = await client.patch(
            f"/experiments/{exp_id}", json={"title": "Взлом"}, headers=auth(t2)
        )
        show_response(r7)

        # ── 8. Каскадное удаление ────────────────────────────────────────────
        hr("8. Каскадное удаление: Experiments → ExperimentRuns → DataSeries → DataPoints")

        # создаём вложенную структуру
        run_r = await client.post(
            f"/experiments/{exp_id}/runs", json={"name": "Запуск 1"}, headers=auth(t1)
        )
        run_id = run_r.json()["run_id"]
        series_r = await client.post(
            f"/runs/{run_id}/series",
            json={"series_name": "Ток", "unit_x": "U, В", "unit_y": "I, А"},
            headers=auth(t1),
        )
        series_id = series_r.json()["series_id"]
        await client.post(
            f"/series/{series_id}/points",
            json={"measurement_order": 1, "x_value": 1.0, "y_value": 0.05},
            headers=auth(t1),
        )

        async with pool.acquire() as conn:
            dp_before = await conn.fetchval(
                'SELECT COUNT(*) FROM "DataPoints" WHERE series_id = $1', series_id
            )
        print(f'\n-- Перед удалением эксперимента')
        print(f'SELECT COUNT(*) FROM "DataPoints" WHERE series_id = {series_id};')
        print(f"  count = {dp_before}")

        show_request("DELETE", f"/experiments/{exp_id}")
        r8 = await client.delete(f"/experiments/{exp_id}", headers=auth(t1))
        show_response(r8)

        async with pool.acquire() as conn:
            dp_after = await conn.fetchval(
                'SELECT COUNT(*) FROM "DataPoints" WHERE series_id = $1', series_id
            )
            run_exists = await conn.fetchval(
                'SELECT COUNT(*) FROM "ExperimentRuns" WHERE run_id = $1', run_id
            )
            exp_exists = await conn.fetchval(
                'SELECT COUNT(*) FROM "Experiments" WHERE experiment_id = $1', exp_id
            )

        print(f'\n-- После удаления эксперимента (прямые запросы к БД):')
        print(f'SELECT COUNT(*) FROM "Experiments"    WHERE experiment_id = {exp_id};  → {exp_exists}')
        print(f'SELECT COUNT(*) FROM "ExperimentRuns" WHERE run_id = {run_id};          → {run_exists}')
        print(f'SELECT COUNT(*) FROM "DataPoints"     WHERE series_id = {series_id};    → {dp_after}')

        show_request("GET", f"/runs/{run_id}  (после удаления эксперимента)")
        r8b = await client.get(f"/runs/{run_id}", headers=auth(t1))
        show_response(r8b)

        show_request("GET", f"/series/{series_id}  (после удаления эксперимента)")
        r8c = await client.get(f"/series/{series_id}", headers=auth(t1))
        show_response(r8c)

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cap_%'")
    print("\n\n-- Тестовые пользователи удалены")
    await close_pool()
    print("\n" + "=" * 64 + "\nГотово.")


asyncio.run(main())
