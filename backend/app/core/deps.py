from datetime import datetime
from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from app.core.db import get_db
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

DbDep = Annotated[asyncpg.Connection, Depends(get_db)]


class UserRecord(BaseModel):
    model_config = {"extra": "ignore"}

    user_id: int
    username: str
    email: str
    created_at: datetime


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbDep,
) -> UserRecord:
    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    row = await db.fetchrow('SELECT * FROM "Users" WHERE user_id = $1', user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return UserRecord(**dict(row))


CurrentUser = Annotated[UserRecord, Depends(get_current_user)]
