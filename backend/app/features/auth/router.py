from fastapi import APIRouter, Form, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select

from app.core.deps import DbDep
from app.core.models import User
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

    model_config = {"from_attributes": True}


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterIn, db: DbDep) -> User:
    existing = await db.scalar(
        select(User).where(or_(User.username == data.username, User.email == data.email))
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username or email already in use")
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.flush()
    return user


@router.post("/login", response_model=TokenOut)
async def login(
    db: DbDep,
    username: str = Form(...),
    password: str = Form(...),
) -> TokenOut:
    user = await db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenOut(access_token=create_access_token(user.user_id))
