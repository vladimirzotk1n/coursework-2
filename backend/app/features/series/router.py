import io
import uuid
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from fastapi import APIRouter, HTTPException, status  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.core.deps import CurrentUser, DbDep  # noqa: E402
from app.core.models import DataPoint, DataSeries, File, SeriesPlotFile  # noqa: E402
from app.features.ownership import get_run_owned, get_series_owned  # noqa: E402
from app.storage.s3 import upload_bytes  # noqa: E402

router = APIRouter(tags=["series"])


class SeriesIn(BaseModel):
    series_name: str = Field(min_length=1, max_length=100)
    unit_x: str | None = Field(default=None, max_length=32)
    unit_y: str | None = Field(default=None, max_length=32)
    description: str | None = None


class SeriesOut(BaseModel):
    series_id: int
    run_id: int
    series_name: str
    unit_x: str | None
    unit_y: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PointIn(BaseModel):
    measurement_order: int = Field(ge=1)
    x_value: float
    y_value: float
    x_uncertainty: float | None = Field(default=None, ge=0)
    y_uncertainty: float | None = Field(default=None, ge=0)


class PointOut(PointIn):
    point_id: int
    series_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class PointsBulkIn(BaseModel):
    points: list[PointIn]


@router.get("/runs/{run_id}/series", response_model=list[SeriesOut])
async def list_series(run_id: int, current: CurrentUser, db: DbDep) -> list[DataSeries]:
    await get_run_owned(db, run_id, current)
    stmt = select(DataSeries).where(DataSeries.run_id == run_id).order_by(DataSeries.series_id)
    return list((await db.scalars(stmt)).all())


@router.post(
    "/runs/{run_id}/series", response_model=SeriesOut, status_code=status.HTTP_201_CREATED
)
async def create_series(
    run_id: int, data: SeriesIn, current: CurrentUser, db: DbDep
) -> DataSeries:
    await get_run_owned(db, run_id, current)
    series = DataSeries(run_id=run_id, **data.model_dump())
    db.add(series)
    await db.flush()
    return series


@router.get("/series/{series_id}", response_model=SeriesOut)
async def get_series(series_id: int, current: CurrentUser, db: DbDep) -> DataSeries:
    return await get_series_owned(db, series_id, current)


@router.patch("/series/{series_id}", response_model=SeriesOut)
async def update_series(
    series_id: int, data: SeriesIn, current: CurrentUser, db: DbDep
) -> DataSeries:
    series = await get_series_owned(db, series_id, current)
    for k, v in data.model_dump().items():
        setattr(series, k, v)
    await db.flush()
    return series


@router.delete("/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(series_id: int, current: CurrentUser, db: DbDep) -> None:
    series = await get_series_owned(db, series_id, current)
    await db.delete(series)


# --- points ---


@router.get("/series/{series_id}/points", response_model=list[PointOut])
async def list_points(series_id: int, current: CurrentUser, db: DbDep) -> list[DataPoint]:
    await get_series_owned(db, series_id, current)
    stmt = (
        select(DataPoint)
        .where(DataPoint.series_id == series_id)
        .order_by(DataPoint.measurement_order.asc())
    )
    return list((await db.scalars(stmt)).all())


@router.put("/series/{series_id}/points", response_model=list[PointOut])
async def replace_points(
    series_id: int, data: PointsBulkIn, current: CurrentUser, db: DbDep
) -> list[DataPoint]:
    await get_series_owned(db, series_id, current)
    orders = [p.measurement_order for p in data.points]
    if len(set(orders)) != len(orders):
        raise HTTPException(status_code=422, detail="measurement_order must be unique")
    await db.execute(delete(DataPoint).where(DataPoint.series_id == series_id))
    rows = [DataPoint(series_id=series_id, **p.model_dump()) for p in data.points]
    db.add_all(rows)
    await db.flush()
    rows.sort(key=lambda r: r.measurement_order)
    return rows


@router.post(
    "/series/{series_id}/points",
    response_model=PointOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_point(
    series_id: int, data: PointIn, current: CurrentUser, db: DbDep
) -> DataPoint:
    await get_series_owned(db, series_id, current)
    point = DataPoint(series_id=series_id, **data.model_dump())
    db.add(point)
    await db.flush()
    return point


@router.delete("/points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_point(point_id: int, current: CurrentUser, db: DbDep) -> None:
    point = await db.get(DataPoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="Point not found")
    await get_series_owned(db, point.series_id, current)
    await db.delete(point)


# --- plot generation ---


def _render_plot(series: DataSeries, points: list[DataPoint]) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = [p.x_value for p in points]
    ys = [p.y_value for p in points]
    xerr = [p.x_uncertainty or 0.0 for p in points]
    yerr = [p.y_uncertainty or 0.0 for p in points]
    ax.errorbar(xs, ys, xerr=xerr, yerr=yerr, fmt="o-", capsize=3)
    ax.set_title(series.series_name)
    if series.unit_x:
        ax.set_xlabel(series.unit_x)
    if series.unit_y:
        ax.set_ylabel(series.unit_y)
    ax.grid(True, alpha=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


@router.post("/series/{series_id}/plot", response_model=SeriesOut)
async def generate_plot(series_id: int, current: CurrentUser, db: DbDep) -> DataSeries:
    series = await get_series_owned(db, series_id, current)
    points = list(
        (
            await db.scalars(
                select(DataPoint)
                .where(DataPoint.series_id == series_id)
                .order_by(DataPoint.measurement_order.asc())
            )
        ).all()
    )
    if not points:
        raise HTTPException(status_code=422, detail="Series has no data points")

    png = _render_plot(series, points)

    # Remove previous plot (junction delete cascades File removal via triggers)
    existing = await db.scalar(
        select(SeriesPlotFile).where(SeriesPlotFile.series_id == series_id)
    )
    if existing is not None:
        await db.delete(existing)
        await db.flush()

    temp_path = f"_uploading/{uuid.uuid4()}.png"
    file = File(mime_type="image/png", storage_path=temp_path, size_bytes=len(png))
    db.add(file)
    await db.flush()
    final_path = f"plots/{series_id}/{file.file_id}.png"
    file.storage_path = final_path
    await db.flush()
    try:
        await upload_bytes(final_path, png, "image/png")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to generate plot: {str(e)}")
    db.add(SeriesPlotFile(series_id=series_id, file_id=file.file_id))
    await db.flush()
    return series
