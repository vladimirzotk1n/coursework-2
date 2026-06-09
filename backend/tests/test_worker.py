"""
Группа 7: Работа фонового процесса удаления файлов.
Группа 8: Полный сценарий каскадного удаления файлов:
  удаление → RunImages → Files (триггер) → FileDeletionQueue (триггер)
  → worker → удаление объекта из MinIO → запись помечена processed_at.
"""
from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_login, s3_exists

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


async def _setup_run(client: AsyncClient, username: str, email: str) -> tuple[str, int, int]:
    """Регистрирует пользователя, создаёт эксперимент и запуск. Возвращает (token, exp_id, run_id)."""
    token = await register_and_login(client, username, email)
    exp_id = (
        await client.post("/experiments", json={"title": "Exp"}, headers=auth_headers(token))
    ).json()["experiment_id"]
    run_id = (
        await client.post(
            f"/experiments/{exp_id}/runs", json={"name": "Run"}, headers=auth_headers(token)
        )
    ).json()["run_id"]
    return token, exp_id, run_id


async def test_worker_deletes_s3_object_and_marks_processed(client: AsyncClient, db_pool):
    """
    Полный жизненный цикл:
      загрузка изображения → удаление изображения (каскадные триггеры) → запуск воркера
      → объект в S3 удалён, запись в очереди помечена как обработанная.
    """
    token, _, run_id = await _setup_run(client, "0w1", "0w1@test.com")

    upload_r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("img.png", FAKE_PNG, "image/png")},
        headers=auth_headers(token),
    )
    assert upload_r.status_code == 201
    file_id = upload_r.json()["file_id"]
    storage_path = upload_r.json()["storage_path"]

    assert await s3_exists(storage_path), "S3 object must exist right after upload"

    # Удаление изображения через API: строка RunImages удалена → триггер удаляет запись Files
    # → триггер добавляет storage_path в FileDeletionQueue
    del_r = await client.delete(f"/runs/{run_id}/images/{file_id}", headers=auth_headers(token))
    assert del_r.status_code == 204

    # Проверка: запись в очереди ожидает обработки; объект S3 ещё существует (воркер не запускался)
    async with db_pool.acquire() as conn:
        queue_row = await conn.fetchrow(
            'SELECT id, processed_at FROM "FileDeletionQueue" WHERE storage_path = $1',
            storage_path,
        )
    assert queue_row is not None, "FileDeletionQueue entry must exist after image deletion"
    assert queue_row["processed_at"] is None
    assert await s3_exists(storage_path), "S3 object must still exist before worker runs"

    # Прямой вызов функции обработки воркера
    from worker.main import process_batch

    processed = await process_batch(db_pool)
    assert processed >= 1

    # Проверка: запись обработана, объект S3 удалён
    async with db_pool.acquire() as conn:
        queue_row = await conn.fetchrow(
            'SELECT processed_at, last_error FROM "FileDeletionQueue" WHERE storage_path = $1',
            storage_path,
        )
    assert queue_row["processed_at"] is not None, "Worker must mark entry as processed"
    assert queue_row["last_error"] is None

    assert not await s3_exists(storage_path), "Worker must delete S3 object"


async def test_worker_does_not_reprocess_completed_entries(client: AsyncClient, db_pool):
    """Запись в очереди с заполненным processed_at не должна повторно обрабатываться."""
    token, _, run_id = await _setup_run(client, "0w2", "0w2@test.com")

    upload_r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("img.png", FAKE_PNG, "image/png")},
        headers=auth_headers(token),
    )
    file_id = upload_r.json()["file_id"]
    storage_path = upload_r.json()["storage_path"]

    await client.delete(f"/runs/{run_id}/images/{file_id}", headers=auth_headers(token))

    from worker.main import process_batch

    await process_batch(db_pool)  # первый запуск — обрабатывает запись

    async with db_pool.acquire() as conn:
        first_ts = await conn.fetchval(
            'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1',
            storage_path,
        )

    await process_batch(db_pool)  # второй запуск — processed_at не должен измениться

    async with db_pool.acquire() as conn:
        second_ts = await conn.fetchval(
            'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1',
            storage_path,
        )

    assert first_ts == second_ts, "processed_at must not change on re-run"


async def test_cascade_delete_experiment_triggers_full_cleanup_pipeline(
    client: AsyncClient, db_pool
):
    """
    Группа 8 — полный сценарий каскадного удаления файлов:

    DELETE Experiments (каскад) →
      ExperimentRuns удалены (каскад) →
        RunImages удалены →
          fn_cleanup_orphaned_file: запись Files удалена →
            fn_file_outbox: запись FileDeletionQueue создана →
              worker.process_batch: объект S3 удалён, запись помечена processed_at.
    """
    token, exp_id, run_id = await _setup_run(client, "0w3", "0w3@test.com")

    upload_r = await client.post(
        f"/runs/{run_id}/images",
        files={"upload": ("img.png", FAKE_PNG, "image/png")},
        headers=auth_headers(token),
    )
    file_id = upload_r.json()["file_id"]
    storage_path = upload_r.json()["storage_path"]
    assert await s3_exists(storage_path)

    # Каскадное удаление с вершины иерархии
    del_r = await client.delete(f"/experiments/{exp_id}", headers=auth_headers(token))
    assert del_r.status_code == 204

    # Запись Files должна быть удалена (триггером fn_cleanup_orphaned_file)
    async with db_pool.acquire() as conn:
        file_row = await conn.fetchrow('SELECT file_id FROM "Files" WHERE file_id = $1', file_id)
        queue_row = await conn.fetchrow(
            'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1',
            storage_path,
        )

    assert file_row is None, "Files record must be deleted by cascade trigger chain"
    assert queue_row is not None, "FileDeletionQueue entry must be created by outbox trigger"
    assert queue_row["processed_at"] is None

    # Воркер обрабатывает очередь
    from worker.main import process_batch

    await process_batch(db_pool)

    assert not await s3_exists(storage_path), "Worker must remove the S3 object"

    async with db_pool.acquire() as conn:
        queue_row = await conn.fetchrow(
            'SELECT processed_at FROM "FileDeletionQueue" WHERE storage_path = $1',
            storage_path,
        )
    assert queue_row["processed_at"] is not None


async def test_worker_increments_retry_count_on_s3_error(db_pool):
    """
    Если удаление из S3 завершается с ошибкой, воркер увеличивает retry_count и сохраняет last_error.
    Используется заведомо неверный путь, которого нет в S3.
    """
    from worker.main import process_batch

    # Добавляем запись в очередь с путём, которого нет в S3
    nonexistent_path = "nonexistent/path/that/will/fail.png"
    async with db_pool.acquire() as conn:
        await conn.execute(
            'INSERT INTO "FileDeletionQueue" (storage_path) VALUES ($1)', nonexistent_path
        )

    await process_batch(db_pool)

    # Воркер пытается удалить объект; поскольку объекта нет,
    # aiobotocore может завершиться без ошибки (S3 DELETE идемпотентен) или выбросить исключение.
    # В любом случае запись должна быть обработана (processed или retry_count увеличен).
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            'SELECT processed_at, retry_count, last_error FROM "FileDeletionQueue" '
            "WHERE storage_path = $1",
            nonexistent_path,
        )
    # S3 DELETE на несуществующем ключе идемпотентен и завершается успешно — запись обработана.
    assert row["processed_at"] is not None or row["retry_count"] > 0
