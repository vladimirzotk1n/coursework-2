"""
Группа 6: Загрузка и удаление файлов в объектном хранилище.
Группа 8 (частично): Триггер каскадного удаления файлов при удалении записи из таблицы-связки.

После удаления последней ссылки на файл из RunImages:
  • fn_cleanup_orphaned_file удаляет запись из Files;
  • fn_file_outbox добавляет storage_path в FileDeletionQueue.
"""
import pytest
from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_login, s3_exists

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


async def _setup_run(client: AsyncClient, username: str, email: str) -> tuple[str, int]:
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


async def test_upload_run_image_stores_in_s3(client: AsyncClient):
    token, run_id = await _setup_run(client, "0f1", "0f1@test.com")

    r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("photo.png", FAKE_PNG, "image/png")},
        headers=auth_headers(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert "file_id" in body
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(FAKE_PNG)
    assert body["storage_path"].startswith(f"images/{run_id}/")
    assert await s3_exists(body["storage_path"])


async def test_list_run_images_returns_urls(client: AsyncClient):
    token, run_id = await _setup_run(client, "0f2", "0f2@test.com")

    for name in ("a.png", "b.png"):
        await client.post(
            f"/runs/{run_id}/images",
            files={"upload": (name, FAKE_PNG, "image/png")},
            headers=auth_headers(token),
        )

    r = await client.get(f"/runs/{run_id}/images", headers=auth_headers(token))
    assert r.status_code == 200
    assert len(r.json()) == 2
    for item in r.json():
        assert "url" in item
        assert item["url"].startswith("http")


async def test_upload_non_image_rejected(client: AsyncClient):
    token, run_id = await _setup_run(client, "0f3", "0f3@test.com")
    r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("doc.pdf", b"%PDF-1.4", "application/pdf")},
        headers=auth_headers(token),
    )
    assert r.status_code == 415


async def test_delete_nonexistent_image_returns_404(client: AsyncClient):
    token, run_id = await _setup_run(client, "0f4", "0f4@test.com")
    r = await client.delete(f"/runs/{run_id}/images/99999", headers=auth_headers(token))
    assert r.status_code == 404


async def test_delete_run_image_removes_files_record(client: AsyncClient, db_pool):
    """
    fn_cleanup_orphaned_file: удаление строки из RunImages (последней ссылки)
    должно также удалять соответствующую запись из Files.
    """
    token, run_id = await _setup_run(client, "0f5", "0f5@test.com")

    upload_r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("img.png", FAKE_PNG, "image/png")},
        headers=auth_headers(token),
    )
    file_id = upload_r.json()["file_id"]

    await client.delete(f"/runs/{run_id}/images/{file_id}", headers=auth_headers(token))

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow('SELECT file_id FROM "Files" WHERE file_id = $1', file_id)
    assert row is None, "Files record must be deleted by trigger when last junction row is removed"


async def test_delete_run_image_enqueues_storage_path(client: AsyncClient, db_pool):
    """
    fn_file_outbox: удаление записи из Files должно добавлять storage_path
    в FileDeletionQueue для последующей очистки S3 воркером.
    """
    token, run_id = await _setup_run(client, "0f6", "0f6@test.com")

    upload_r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("img.png", FAKE_PNG, "image/png")},
        headers=auth_headers(token),
    )
    file_id = upload_r.json()["file_id"]
    storage_path = upload_r.json()["storage_path"]

    await client.delete(f"/runs/{run_id}/images/{file_id}", headers=auth_headers(token))

    async with db_pool.acquire() as conn:
        queue_row = await conn.fetchrow(
            'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1',
            storage_path,
        )
    assert queue_row is not None, "FileDeletionQueue entry must be created by trigger"
    assert queue_row["processed_at"] is None, "Entry must be pending (unprocessed)"
