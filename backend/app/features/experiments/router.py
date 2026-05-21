from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser, DbDep
from app.features.ownership import get_experiment_owned

router = APIRouter(prefix="/experiments", tags=["experiments"])


class ExperimentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ExperimentOut(BaseModel):
    experiment_id: int
    user_id: int
    title: str
    description: str | None
    created_at: datetime
    updated_at: datetime


@router.get("", response_model=list[ExperimentOut])
async def list_experiments(current: CurrentUser, db: DbDep) -> list[dict]:
    rows = await db.fetch(
        'SELECT * FROM "Experiments" WHERE user_id = $1 ORDER BY created_at DESC',
        current.user_id,
    )
    return [dict(r) for r in rows]


@router.post("", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
async def create_experiment(data: ExperimentIn, current: CurrentUser, db: DbDep) -> dict:
    row = await db.fetchrow(
        'INSERT INTO "Experiments" (user_id, title, description) VALUES ($1, $2, $3) RETURNING *',
        current.user_id,
        data.title,
        data.description,
    )
    return dict(row)


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(experiment_id: int, current: CurrentUser, db: DbDep) -> dict:
    return await get_experiment_owned(db, experiment_id, current)


@router.patch("/{experiment_id}", response_model=ExperimentOut)
async def update_experiment(
    experiment_id: int, data: ExperimentIn, current: CurrentUser, db: DbDep
) -> dict:
    await get_experiment_owned(db, experiment_id, current)
    row = await db.fetchrow(
        """UPDATE "Experiments" SET title = $1, description = $2
           WHERE experiment_id = $3 RETURNING *""",
        data.title,
        data.description,
        experiment_id,
    )
    return dict(row)


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experiment(experiment_id: int, current: CurrentUser, db: DbDep) -> None:
    await get_experiment_owned(db, experiment_id, current)
    await db.execute('DELETE FROM "Experiments" WHERE experiment_id = $1', experiment_id)
