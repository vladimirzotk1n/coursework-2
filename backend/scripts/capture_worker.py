"""
Запуск: docker compose run --rm backend python scripts/capture_worker.py
"""
import asyncio
import json

from httpx import ASGITransport, AsyncClient

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

def hr(label):
    print(f"\n{'─'*64}\n# {label}")

async def register_and_login(client, username, email, password="secret123"):
    await client.post("/auth/register", json={"username": username, "email": email, "password": password})
    r = await client.post("/auth/login", data={"username": username, "password": password})
    return r.json()["access_token"]

def auth(token):
    return {"Authorization": f"Bearer {token}"}

async def setup_run(client, token):
    exp_id = (await client.post("/experiments", json={"title": "Exp"}, headers=auth(token))).json()["experiment_id"]
    run_id = (await client.post(f"/experiments/{exp_id}/runs", json={"name": "Run"}, headers=auth(token))).json()["run_id"]
    return exp_id, run_id

async def upload_image(client, token, run_id):
    r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("img.png", FAKE_PNG, "image/png")},
        headers=auth(token),
    )
    return r.json()["file_id"], r.json()["storage_path"]

async def s3_exists(storage_path):
    from app.core.config import settings
    from app.storage.s3 import s3_client
    async with s3_client() as s3:
        try:
            await s3.head_object(Bucket=settings.s3_bucket, Key=storage_path)
            return True
        except Exception:
            return False

async def main():
    from app.core import db as db_module
    from app.core.db import apply_schema, close_pool, get_pool
    from app.main import app as fastapi_app
    from app.storage import s3 as s3_module
    from app.storage.s3 import ensure_bucket
    from worker.main import process_batch

    db_module._pool = None
    s3_module._session = None
    await apply_schema()
    await ensure_bucket()
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cwrk_%'")
        # помечаем старые необработанные записи как выполненные,
        # чтобы батч гарантированно дошёл до тестовых записей
        await conn.execute('UPDATE "FileDeletionQueue" SET processed_at = NOW() WHERE processed_at IS NULL')

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        token = await register_and_login(client, "_cwrk_alice", "_cwrk_alice@test.com")

        # ── 1. Полный жизненный цикл: загрузка → удаление → воркер ──────────
        hr("1. Жизненный цикл: загрузка → удаление → process_batch → MinIO")
        _, run_id = await setup_run(client, token)
        file_id, storage_path = await upload_image(client, token, run_id)

        print(f"\n  Загружен файл: file_id={file_id}  storage_path={storage_path!r}")
        print(f"  Объект в MinIO существует: {await s3_exists(storage_path)}")

        await client.delete(f"/runs/{run_id}/images/{file_id}", headers=auth(token))

        async with pool.acquire() as conn:
            q = await conn.fetchrow(
                'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1', storage_path
            )
        print(f"\n-- После DELETE /runs/{run_id}/images/{file_id}  (HTTP 204):")
        print(f'   SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = {storage_path!r};')
        print(f"   processed_at={q['processed_at']}   (воркер ещё не запускался)")
        print(f"   Объект в MinIO существует: {await s3_exists(storage_path)}")

        processed = await process_batch(pool)
        print(f"\n-- После process_batch()  (обработано записей: {processed}):")

        async with pool.acquire() as conn:
            q2 = await conn.fetchrow(
                'SELECT processed_at, last_error FROM "FileDeletionQueue" WHERE storage_path = $1', storage_path
            )
        print(f'   SELECT processed_at, last_error FROM "FileDeletionQueue" WHERE storage_path = {storage_path!r};')
        print(f"   processed_at={str(q2['processed_at'])[:23]}  last_error={q2['last_error']}")
        print(f"   Объект в MinIO существует: {await s3_exists(storage_path)}")

        # ── 2. Идемпотентность: повторный запуск не меняет processed_at ─────
        hr("2. Идемпотентность: повторный вызов process_batch не меняет processed_at")
        ts_first = q2['processed_at']
        await process_batch(pool)
        async with pool.acquire() as conn:
            ts_second = await conn.fetchval(
                'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1', storage_path
            )
        print(f"\n  processed_at после первого запуска:    {str(ts_first)[:23]}")
        print(f"  processed_at после повторного запуска: {str(ts_second)[:23]}")
        print(f"  Значения совпадают: {ts_first == ts_second}")

        # ── 3. Каскадное удаление эксперимента → полная цепочка ────────────
        hr("3. Каскадное удаление эксперимента: Experiments → RunImages → Files → FileDeletionQueue → MinIO")
        exp_id, run_id2 = await setup_run(client, token)
        file_id2, storage_path2 = await upload_image(client, token, run_id2)
        print(f"\n  Загружен файл: file_id={file_id2}  storage_path={storage_path2!r}")
        print(f"  Объект в MinIO существует: {await s3_exists(storage_path2)}")

        # сбрасываем очередь перед тестом
        async with pool.acquire() as conn:
            await conn.execute('UPDATE "FileDeletionQueue" SET processed_at = NOW() WHERE processed_at IS NULL')

        print(f"\nDELETE /experiments/{exp_id}  →  ", end="")
        rd2 = await client.delete(f"/experiments/{exp_id}", headers=auth(token))
        print(f"HTTP {rd2.status_code}")

        async with pool.acquire() as conn:
            exp_exists = await conn.fetchval('SELECT COUNT(*) FROM "Experiments" WHERE experiment_id = $1', exp_id)
            run_exists = await conn.fetchval('SELECT COUNT(*) FROM "ExperimentRuns" WHERE run_id = $1', run_id2)
            file_exists = await conn.fetchval('SELECT COUNT(*) FROM "Files" WHERE file_id = $1', file_id2)
            queue_row = await conn.fetchrow(
                'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1', storage_path2
            )

        print(f'\n-- Прямые запросы к БД после DELETE /experiments/{exp_id}:')
        print(f'   SELECT COUNT(*) FROM "Experiments"    WHERE experiment_id = {exp_id};   -- {exp_exists}')
        print(f'   SELECT COUNT(*) FROM "ExperimentRuns" WHERE run_id = {run_id2};           -- {run_exists}')
        print(f'   SELECT COUNT(*) FROM "Files"           WHERE file_id = {file_id2};         -- {file_exists}')
        print(f'   SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = {storage_path2!r};')
        print(f'   processed_at={queue_row["processed_at"]}   (задача ожидает воркера)')
        print(f'   Объект в MinIO существует: {await s3_exists(storage_path2)}')

        await process_batch(pool)

        async with pool.acquire() as conn:
            queue_row2 = await conn.fetchrow(
                'SELECT processed_at, last_error FROM "FileDeletionQueue" WHERE storage_path = $1', storage_path2
            )
        print(f'\n-- После process_batch():')
        print(f'   processed_at={str(queue_row2["processed_at"])[:23]}  last_error={queue_row2["last_error"]}')
        print(f'   Объект в MinIO существует: {await s3_exists(storage_path2)}')

        # ── 4. Несуществующий путь в очереди ────────────────────────────────
        hr("4. Несуществующий путь в S3 — запись помечается обработанной или retry_count растёт")
        bad_path = "nonexistent/path/file.png"
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO "FileDeletionQueue" (storage_path) VALUES ($1)', bad_path)
        print(f"\n  Добавлена запись с путём {bad_path!r}")

        await process_batch(pool)

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT processed_at, retry_count, last_error FROM "FileDeletionQueue" WHERE storage_path = $1',
                bad_path,
            )
        print(f'   SELECT processed_at, retry_count, last_error FROM "FileDeletionQueue"')
        print(f'          WHERE storage_path = {bad_path!r};')
        print(f"   processed_at={row['processed_at']}  retry_count={row['retry_count']}  last_error={row['last_error']}")

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cwrk_%'")
    await close_pool()
    print("\n" + "="*64 + "\nГотово.")

asyncio.run(main())
