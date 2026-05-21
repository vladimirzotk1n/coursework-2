from fastapi import APIRouter, Form, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.core.deps import DbDep
from app.core.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    user_id: int
    username: str
    email: EmailStr


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, db: DbDep) -> dict:
    existing = await db.fetchrow(
        'SELECT user_id FROM "Users" WHERE username = $1 OR email = $2',
        data.username,
        data.email,
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username or email already in use")
    row = await db.fetchrow(
        'INSERT INTO "Users" (username, email, password_hash) VALUES ($1, $2, $3) RETURNING *',
        data.username,
        data.email,
        hash_password(data.password),
    )
    return dict(row)


@router.post("/login", response_model=TokenOut)
async def login(
    db: DbDep,
    username: str = Form(...),
    password: str = Form(...),
) -> TokenOut:
    row = await db.fetchrow('SELECT * FROM "Users" WHERE username = $1', username)
    if row is None or not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenOut(access_token=create_access_token(row["user_id"]))
