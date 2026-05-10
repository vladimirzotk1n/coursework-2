from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr

from app.core.deps import CurrentUser

router = APIRouter(prefix="/users", tags=["users"])


class MeOut(BaseModel):
    user_id: int
    username: str
    email: EmailStr
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("/me", response_model=MeOut)
async def me(current: CurrentUser) -> MeOut:
    return MeOut.model_validate(current)
