import asyncpg
from fastapi import HTTPException

from app.core.deps import UserRecord


async def get_experiment_owned(
    db: asyncpg.Connection, experiment_id: int, user: UserRecord
) -> dict:
    row = await db.fetchrow(
        'SELECT * FROM "Experiments" WHERE experiment_id = $1 AND user_id = $2',
        experiment_id,
        user.user_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return dict(row)


async def get_run_owned(db: asyncpg.Connection, run_id: int, user: UserRecord) -> dict:
    row = await db.fetchrow(
        """
        SELECT r.* FROM "ExperimentRuns" r
          JOIN "Experiments" e ON e.experiment_id = r.experiment_id
        WHERE r.run_id = $1 AND e.user_id = $2
        """,
        run_id,
        user.user_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)


async def get_series_owned(db: asyncpg.Connection, series_id: int, user: UserRecord) -> dict:
    row = await db.fetchrow(
        """
        SELECT s.* FROM "DataSeries" s
          JOIN "ExperimentRuns" r ON r.run_id = s.run_id
          JOIN "Experiments" e ON e.experiment_id = r.experiment_id
        WHERE s.series_id = $1 AND e.user_id = $2
        """,
        series_id,
        user.user_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Series not found")
    return dict(row)


async def get_report_owned(db: asyncpg.Connection, report_id: int, user: UserRecord) -> dict:
    row = await db.fetchrow(
        """
        SELECT rp.* FROM "Reports" rp
          JOIN "ExperimentRuns" r ON r.run_id = rp.run_id
          JOIN "Experiments" e ON e.experiment_id = r.experiment_id
        WHERE rp.report_id = $1 AND e.user_id = $2
        """,
        report_id,
        user.user_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return dict(row)
