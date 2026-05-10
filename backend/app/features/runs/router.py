from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import CurrentUser, DbDep
from app.core.models import ExperimentRun
from app.features.ownership import get_experiment_owned, get_run_owned

router = APIRouter(tags=["runs"])


class RunIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class RunOut(BaseModel):
    run_id: int
    experiment_id: int
    run_number: int
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("/experiments/{experiment_id}/runs", response_model=list[RunOut])
async def list_runs(experiment_id: int, current: CurrentUser, db: DbDep) -> list[ExperimentRun]:
    await get_experiment_owned(db, experiment_id, current)
    stmt = (
        select(ExperimentRun)
        .where(ExperimentRun.experiment_id == experiment_id)
        .order_by(ExperimentRun.run_number.asc())
    )
    return list((await db.scalars(stmt)).all())


@router.post(
    "/experiments/{experiment_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    experiment_id: int, data: RunIn, current: CurrentUser, db: DbDep
) -> ExperimentRun:
    await get_experiment_owned(db, experiment_id, current)
    run = ExperimentRun(
        experiment_id=experiment_id,
        run_number=0,  # overwritten by trg_run_number
        name=data.name,
        description=data.description,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return run


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: int, current: CurrentUser, db: DbDep) -> ExperimentRun:
    return await get_run_owned(db, run_id, current)


@router.patch("/runs/{run_id}", response_model=RunOut)
async def update_run(
    run_id: int, data: RunIn, current: CurrentUser, db: DbDep
) -> ExperimentRun:
    run = await get_run_owned(db, run_id, current)
    run.name = data.name
    run.description = data.description
    await db.flush()
    return run


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: int, current: CurrentUser, db: DbDep) -> None:
    run = await get_run_owned(db, run_id, current)
    await db.delete(run)
