"""
Скрипт для получения реального вывода тестов аутентификации.
Запуск: docker compose run --rm backend python scripts/capture_auth.py

Использует уже запущенные postgres и minio из docker-compose.
Создаёт тестовых пользователей с префиксом _capture_ и удаляет их в конце.
"""
import asyncio
import json
import re

import asyncpg
from httpx import ASGITransport, AsyncClient


def hr(label: str):
    print(f"\n{'─' * 64}")
    print(f"# {label}")


def show_request(method: str, path: str, body=None, form=None):
    print(f"\n{method} {path}")
    if body:
        print(json.dumps(body, ensure_ascii=False, indent=2))
    if form:
        print("  " + "&".join(f"{k}={v}" for k, v in form.items()))


def show_response(response):
    print(f"\nHTTP {response.status_code}")
    try:
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    except Exception:
        print(response.text[:300])


async def show_users(conn, label: str):
    rows = await conn.fetch(
        "SELECT user_id, username, email FROM \"Users\""
        " WHERE username LIKE '_capture_%' ORDER BY user_id"
    )
    print(f"\n-- {label}")
    print("SELECT user_id, username, email FROM \"Users\" WHERE username LIKE '_capture_%';")
    if rows:
        print(f" {'user_id':>7} | {'username':<16} | email")
        print(f"---------+------------------+------------------------")
        for r in rows:
            print(f" {r['user_id']:>7} | {r['username']:<16} | {r['email']}")
    else:
        print(" (0 rows)")


async def main():
    from app.core import config as cfg_module
    from app.core import db as db_module
    from app.core.db import apply_schema, close_pool, get_pool
    from app.main import app as fastapi_app
    from app.storage import s3 as s3_module
    from app.storage.s3 import ensure_bucket

    # Используем настройки из env (DATABASE_URL, S3_* уже заданы в docker-compose)
    db_module._pool = None
    s3_module._session = None

    await apply_schema()
    await ensure_bucket()

    pool = await get_pool()

    # Чистим тестовых пользователей если остались от прошлого запуска
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_capture_%'")

    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app), base_url="http://test"
    ) as client:

        # ── 1. Регистрация нового пользователя ──────────────────────────────
        hr("1. Регистрация нового пользователя (корректные данные)")
        body = {"username": "_capture_alice", "email": "_capture_alice@test.com",
                "password": "secret123"}
        show_request("POST", "/auth/register", body)
        r = await client.post("/auth/register", json=body)
        show_response(r)
        async with pool.acquire() as conn:
            await show_users(conn, "Таблица Users после регистрации")

        # ── 2. Дублирование username ─────────────────────────────────────────
        hr("2. Попытка регистрации с уже занятым username")
        body2 = {"username": "_capture_alice", "email": "_capture_other@test.com",
                 "password": "pass1234"}
        show_request("POST", "/auth/register", body2)
        r2 = await client.post("/auth/register", json=body2)
        show_response(r2)
        async with pool.acquire() as conn:
            await show_users(conn, "Таблица Users — новая строка не добавлена")

        # ── 3. Дублирование email ────────────────────────────────────────────
        hr("3. Попытка регистрации с уже занятым email")
        body3 = {"username": "_capture_alice2", "email": "_capture_alice@test.com",
                 "password": "pass1234"}
        show_request("POST", "/auth/register", body3)
        r3 = await client.post("/auth/register", json=body3)
        show_response(r3)

        # ── 4. Слишком короткий пароль ───────────────────────────────────────
        hr("4. Регистрация с паролем короче допустимого минимума")
        body4 = {"username": "_capture_dave", "email": "_capture_dave@test.com", "password": "123"}
        show_request("POST", "/auth/register", body4)
        r4 = await client.post("/auth/register", json=body4)
        show_response(r4)
        async with pool.acquire() as conn:
            await show_users(conn, "Таблица Users — dave не добавлен")

        # ── 5. Успешный вход ─────────────────────────────────────────────────
        hr("5. Успешный вход в систему")
        show_request("POST", "/auth/login", form={"username": "_capture_alice",
                                                   "password": "secret123"})
        r5 = await client.post(
            "/auth/login", data={"username": "_capture_alice", "password": "secret123"}
        )
        show_response(r5)
        token = r5.json()["access_token"]
        print(f"\n  (токен сохранён для следующих запросов)")

        # ── 6. Неверный пароль ───────────────────────────────────────────────
        hr("6. Вход с неверным паролем")
        show_request("POST", "/auth/login", form={"username": "_capture_alice",
                                                   "password": "wrongpass"})
        r6 = await client.post(
            "/auth/login", data={"username": "_capture_alice", "password": "wrongpass"}
        )
        show_response(r6)

        # ── 7. Несуществующий пользователь ──────────────────────────────────
        hr("7. Вход несуществующего пользователя")
        show_request("POST", "/auth/login", form={"username": "nobody", "password": "anything"})
        r7 = await client.post("/auth/login", data={"username": "nobody", "password": "anything"})
        show_response(r7)

        # ── 8. Действительный токен ──────────────────────────────────────────
        hr("8. Запрос к защищённому ресурсу с действительным токеном")
        show_request("GET", "/experiments")
        print(f"  Authorization: Bearer {token[:40]}...")
        r8 = await client.get("/experiments", headers={"Authorization": f"Bearer {token}"})
        show_response(r8)

        # ── 9. Без токена ────────────────────────────────────────────────────
        hr("9. Запрос к защищённому ресурсу без заголовка авторизации")
        show_request("GET", "/experiments")
        r9 = await client.get("/experiments")
        show_response(r9)

        # ── 10. Недействительный токен ───────────────────────────────────────
        hr("10. Запрос с недействительным токеном")
        show_request("GET", "/experiments")
        print("  Authorization: Bearer this.is.invalid")
        r10 = await client.get(
            "/experiments", headers={"Authorization": "Bearer this.is.invalid"}
        )
        show_response(r10)

        # ── 11. Нераспознанная схема ─────────────────────────────────────────
        hr("11. Нераспознанная схема авторизации")
        show_request("GET", "/experiments")
        print("  Authorization: Token somevalue")
        r11 = await client.get(
            "/experiments", headers={"Authorization": "Token somevalue"}
        )
        show_response(r11)

    # Чистим тестовых пользователей
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_capture_%'")
    print("\n\n-- Тестовые пользователи удалены из базы данных")

    await close_pool()
    print("\n" + "=" * 64)
    print("Готово.")


asyncio.run(main())
