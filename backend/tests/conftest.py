from __future__ import annotations

import re

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.minio import MinioContainer
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="session")
def mc_container():
    with MinioContainer() as mc:
        yield mc


@pytest.fixture
async def client(pg_container, mc_container):
    """
    HTTP-клиент для каждого теста, использующий реальные контейнеры PostgreSQL и MinIO.

    Жизненный цикл для каждого теста:
      1. Патч глобальных настроек — адреса контейнеров.
      2. Сброс ленивых глобалов (пул соединений, S3-сессия).
      3. Применение схемы (идемпотентный DDL) и создание S3-бакета.
      4. Очистка всех таблиц данных — каждый тест стартует с чистого листа.
      5. Yield httpx.AsyncClient, подключённого к FastAPI-приложению.
      6. Закрытие пула соединений.
    """
    from app.core import config as cfg_module
    from app.core import db as db_module
    from app.core.db import apply_schema, close_pool, get_pool
    from app.main import app as fastapi_app
    from app.storage import s3 as s3_module
    from app.storage.s3 import ensure_bucket

    # --- патч настроек ---
    pg_raw = pg_container.get_connection_url()
    pg_url = re.sub(r"postgresql(\+\w+)?://", "postgresql+asyncpg://", pg_raw)
    cfg_module.settings.database_url = pg_url

    minio_host = mc_container.get_container_host_ip()
    minio_port = mc_container.get_exposed_port(9000)
    minio_url = f"http://{minio_host}:{minio_port}"
    cfg_module.settings.s3_endpoint_url = minio_url
    cfg_module.settings.s3_public_endpoint_url = minio_url
    cfg_module.settings.s3_access_key = mc_container.access_key
    cfg_module.settings.s3_secret_key = mc_container.secret_key
    cfg_module.settings.s3_bucket = "test-experiments"

    # --- сброс ленивых глобалов для переподключения с новыми настройками ---
    db_module._pool = None
    s3_module._session = None

    # --- одноразовая инициализация (идемпотентно) ---
    await apply_schema()
    await ensure_bucket()

    # --- чистое состояние перед каждым тестом ---
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('TRUNCATE "Users" CASCADE')
        await conn.execute('TRUNCATE "FileDeletionQueue"')

    # --- запуск теста ---
    async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as c:
        yield c

    await close_pool()


@pytest.fixture
async def db_pool(client):
    """Прямой asyncpg-пул — для тестов, проверяющих состояние БД напрямую."""
    from app.core.db import get_pool

    return await get_pool()
