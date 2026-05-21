from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser, DbDep
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


@router.get("/experiments/{experiment_id}/runs", response_model=list[RunOut])
async def list_runs(experiment_id: int, current: CurrentUser, db: DbDep) -> list[dict]:
    await get_experiment_owned(db, experiment_id, current)
    rows = await db.fetch(
        'SELECT * FROM "ExperimentRuns" WHERE experiment_id = $1 ORDER BY run_number ASC',
        experiment_id,
    )
    return [dict(r) for r in rows]


@router.post(
    "/experiments/{experiment_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(experiment_id: int, data: RunIn, current: CurrentUser, db: DbDep) -> dict:
    await get_experiment_owned(db, experiment_id, current)
    # run_number=0 -> replaced by trg_run_number; RETURNING * reflects post-trigger value
    row = await db.fetchrow(
        """INSERT INTO "ExperimentRuns" (experiment_id, run_number, name, description)
           VALUES ($1, 0, $2, $3) RETURNING *""",
        experiment_id,
        data.name,
        data.description,
    )
    return dict(row)


@router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: int, current: CurrentUser, db: DbDep) -> dict:
    return await get_run_owned(db, run_id, current)


@router.patch("/runs/{run_id}", response_model=RunOut)
async def update_run(run_id: int, data: RunIn, current: CurrentUser, db: DbDep) -> dict:
    await get_run_owned(db, run_id, current)
    row = await db.fetchrow(
        'UPDATE "ExperimentRuns" SET name = $1, description = $2 WHERE run_id = $3 RETURNING *',
        data.name,
        data.description,
        run_id,
    )
    return dict(row)


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: int, current: CurrentUser, db: DbDep) -> None:
    await get_run_owned(db, run_id, current)
    await db.execute('DELETE FROM "ExperimentRuns" WHERE run_id = $1', run_id)
