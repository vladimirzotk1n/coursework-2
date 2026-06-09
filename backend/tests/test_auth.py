"""
Группа 1: Регистрация пользователей и аутентификация.
Группа 2: Корректность работы JWT-токенов.
"""
from httpx import AsyncClient

from tests.helpers import auth_headers, register_and_login


async def test_register_returns_user_data(client: AsyncClient):
    r = await client.post(
        "/auth/register",
        json={"username": "alice", "email": "alice@test.com", "password": "secret123"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@test.com"
    assert "user_id" in body
    assert "password_hash" not in body


async def test_register_duplicate_username_rejected(client: AsyncClient):
    payload = {"username": "bob", "email": "bob@test.com", "password": "pass1234"}
    await client.post("/auth/register", json=payload)
    r = await client.post(
        "/auth/register",
        json={**payload, "email": "other@test.com"},
    )
    assert r.status_code == 409


async def test_register_duplicate_email_rejected(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"username": "carol", "email": "carol@test.com", "password": "pass1234"},
    )
    r = await client.post(
        "/auth/register",
        json={"username": "carol2", "email": "carol@test.com", "password": "pass1234"},
    )
    assert r.status_code == 409


async def test_register_short_password_rejected(client: AsyncClient):
    r = await client.post(
        "/auth/register",
        json={"username": "dave", "email": "dave@test.com", "password": "123"},
    )
    assert r.status_code == 422


async def test_login_returns_bearer_token(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"username": "eve", "email": "eve@test.com", "password": "mypassword"},
    )
    r = await client.post(
        "/auth/login",
        data={"username": "eve", "password": "mypassword"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


async def test_login_wrong_password_rejected(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={"username": "frank", "email": "frank@test.com", "password": "rightpass"},
    )
    r = await client.post(
        "/auth/login",
        data={"username": "frank", "password": "wrongpass"},
    )
    assert r.status_code == 401


async def test_login_nonexistent_user_rejected(client: AsyncClient):
    r = await client.post(
        "/auth/login",
        data={"username": "nobody", "password": "anything"},
    )
    assert r.status_code == 401


async def test_valid_token_grants_access(client: AsyncClient):
    token = await register_and_login(client, "grace", "grace@test.com")
    r = await client.get("/experiments", headers=auth_headers(token))
    assert r.status_code == 200


async def test_missing_token_returns_401(client: AsyncClient):
    r = await client.get("/experiments")
    assert r.status_code == 401


async def test_invalid_token_returns_401(client: AsyncClient):
    r = await client.get(
        "/experiments",
        headers={"Authorization": "Bearer this.is.invalid"},
    )
    assert r.status_code == 401


async def test_malformed_auth_header_returns_401(client: AsyncClient):
    r = await client.get(
        "/experiments",
        headers={"Authorization": "Token somevalue"},
    )
    assert r.status_code == 401
