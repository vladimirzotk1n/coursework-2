"""Общие утилиты для тестов (не pytest-фикстуры)."""
from __future__ import annotations

from httpx import AsyncClient


async def register_and_login(
    client: AsyncClient,
    username: str,
    email: str,
    password: str = "password123",
) -> str:
    """Регистрирует пользователя и возвращает валидный JWT access token."""
    r = await client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert r.status_code == 201, f"register failed: {r.text}"
    r = await client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def s3_exists(key: str) -> bool:
    """Возвращает True, если объект существует в тестовом S3-бакете."""
    from app.core.config import settings
    from app.storage.s3 import s3_client

    async with s3_client() as s3:
        try:
            await s3.head_object(Bucket=settings.s3_bucket, Key=key)
            return True
        except Exception:
            return False
