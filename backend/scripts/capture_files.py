"""
Запуск: docker compose run --rm backend python scripts/capture_files.py
"""
import asyncio
import json

from httpx import ASGITransport, AsyncClient

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

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
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cfile_%'")

    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as client:
        token = await register_and_login(client, "_cfile_alice", "_cfile_alice@test.com")
        run_id = await setup_run(client, token)

        # ── 1. Загрузка изображения ──────────────────────────────────────────
        hr("1. Загрузка изображения — запись в Files и объект в MinIO")
        print(f"\nPOST /runs/{run_id}/images  (multipart/form-data, photo.png, image/png, {len(FAKE_PNG)} bytes)")
        r1 = await client.post(
            f"/runs/{run_id}/images",
            files={"upload": ("photo.png", FAKE_PNG, "image/png")},
            headers=auth(token),
        )
        show_resp(r1)
        file_id = r1.json()["file_id"]
        storage_path = r1.json()["storage_path"]

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT file_id, storage_path, mime_type, size_bytes FROM "Files" WHERE file_id = $1',
                file_id,
            )
        print(f'\n-- SELECT file_id, storage_path, mime_type, size_bytes FROM "Files" WHERE file_id = {file_id};')
        print(f"   file_id={row['file_id']}  storage_path={row['storage_path']!r}  mime_type={row['mime_type']!r}  size_bytes={row['size_bytes']}")

        # ── 2. Недопустимый тип файла ────────────────────────────────────────
        hr("2. Попытка загрузить файл недопустимого типа (PDF)")
        print(f"\nPOST /runs/{run_id}/images  (doc.pdf, application/pdf)")
        r2 = await client.post(
            f"/runs/{run_id}/images",
            files={"upload": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth(token),
        )
        show_resp(r2)

        async with pool.acquire() as conn:
            files_count = await conn.fetchval('SELECT COUNT(*) FROM "Files"')
        print(f'\n-- SELECT COUNT(*) FROM "Files";  -- {files_count}  (без изменений)')

        # ── 3. Удаление — триггеры fn_cleanup_orphaned_file и fn_file_outbox ─
        hr("3. Удаление изображения — срабатывание каскадных триггеров")

        async with pool.acquire() as conn:
            before_files = await conn.fetchval('SELECT COUNT(*) FROM "Files" WHERE file_id = $1', file_id)
            before_queue = await conn.fetchval('SELECT COUNT(*) FROM "FileDeletionQueue" WHERE storage_path = $1', storage_path)
        print(f'\n-- До удаления:')
        print(f'   SELECT COUNT(*) FROM "Files"             WHERE file_id = {file_id};       -- {before_files}')
        print(f'   SELECT COUNT(*) FROM "FileDeletionQueue" WHERE storage_path = {storage_path!r};  -- {before_queue}')

        print(f"\nDELETE /runs/{run_id}/images/{file_id}")
        rd = await client.delete(f"/runs/{run_id}/images/{file_id}", headers=auth(token))
        show_resp(rd)

        async with pool.acquire() as conn:
            after_files = await conn.fetchval('SELECT COUNT(*) FROM "Files" WHERE file_id = $1', file_id)
            queue_row = await conn.fetchrow(
                'SELECT storage_path, processed_at FROM "FileDeletionQueue" WHERE storage_path = $1',
                storage_path,
            )
        print(f'\n-- После удаления:')
        print(f'   SELECT COUNT(*) FROM "Files" WHERE file_id = {file_id};  -- {after_files}')
        print(f'   SELECT storage_path, processed_at FROM "FileDeletionQueue"')
        print(f'          WHERE storage_path = {storage_path!r};')
        print(f'   storage_path={queue_row["storage_path"]!r}  processed_at={queue_row["processed_at"]}')

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM \"Users\" WHERE username LIKE '_cfile_%'")
    await close_pool()
    print("\n" + "="*64 + "\nГотово.")

asyncio.run(main())
