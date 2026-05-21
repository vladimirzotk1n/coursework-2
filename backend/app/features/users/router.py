from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from app.core.deps import CurrentUser

router = APIRouter(prefix="/users", tags=["users"])


class MeOut(BaseModel):
    user_id: int
    username: str
    email: EmailStr


@router.get("/me", response_model=MeOut)
async def me(current: CurrentUser) -> MeOut:
    return MeOut(user_id=current.user_id, username=current.username, email=current.email)
