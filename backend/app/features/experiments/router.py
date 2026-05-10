from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import CurrentUser, DbDep
from app.core.models import Experiment
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

    model_config = {"from_attributes": True}


@router.get("", response_model=list[ExperimentOut])
async def list_experiments(current: CurrentUser, db: DbDep) -> list[Experiment]:
    stmt = select(Experiment).where(Experiment.user_id == current.user_id).order_by(
        Experiment.created_at.desc()
    )
    return list((await db.scalars(stmt)).all())


@router.post("", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
async def create_experiment(data: ExperimentIn, current: CurrentUser, db: DbDep) -> Experiment:
    exp = Experiment(user_id=current.user_id, title=data.title, description=data.description)
    db.add(exp)
    await db.flush()
    return exp


@router.get("/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(experiment_id: int, current: CurrentUser, db: DbDep) -> Experiment:
    return await get_experiment_owned(db, experiment_id, current)


@router.patch("/{experiment_id}", response_model=ExperimentOut)
async def update_experiment(
    experiment_id: int, data: ExperimentIn, current: CurrentUser, db: DbDep
) -> Experiment:
    exp = await get_experiment_owned(db, experiment_id, current)
    exp.title = data.title
    exp.description = data.description
    await db.flush()
    return exp


@router.delete("/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experiment(experiment_id: int, current: CurrentUser, db: DbDep) -> None:
    exp = await get_experiment_owned(db, experiment_id, current)
    await db.delete(exp)
