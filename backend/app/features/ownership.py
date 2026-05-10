from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import DataSeries, Experiment, ExperimentRun, Report, User


async def get_experiment_owned(db: AsyncSession, experiment_id: int, user: User) -> Experiment:
    exp = await db.get(Experiment, experiment_id)
    if exp is None or exp.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


async def get_run_owned(db: AsyncSession, run_id: int, user: User) -> ExperimentRun:
    stmt = (
        select(ExperimentRun)
        .join(Experiment, Experiment.experiment_id == ExperimentRun.experiment_id)
        .where(ExperimentRun.run_id == run_id, Experiment.user_id == user.user_id)
    )
    run = await db.scalar(stmt)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


async def get_series_owned(db: AsyncSession, series_id: int, user: User) -> DataSeries:
    stmt = (
        select(DataSeries)
        .join(ExperimentRun, ExperimentRun.run_id == DataSeries.run_id)
        .join(Experiment, Experiment.experiment_id == ExperimentRun.experiment_id)
        .where(DataSeries.series_id == series_id, Experiment.user_id == user.user_id)
    )
    series = await db.scalar(stmt)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")
    return series


async def get_report_owned(db: AsyncSession, report_id: int, user: User) -> Report:
    stmt = (
        select(Report)
        .join(ExperimentRun, ExperimentRun.run_id == Report.run_id)
        .join(Experiment, Experiment.experiment_id == ExperimentRun.experiment_id)
        .where(Report.report_id == report_id, Experiment.user_id == user.user_id)
    )
    report = await db.scalar(stmt)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
