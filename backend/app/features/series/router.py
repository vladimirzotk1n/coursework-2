import io
import uuid
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from fastapi import APIRouter, HTTPException, status  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app.core.deps import CurrentUser, DbDep  # noqa: E402
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


class PointsBulkIn(BaseModel):
    points: list[PointIn]


@router.get("/runs/{run_id}/series", response_model=list[SeriesOut])
async def list_series(run_id: int, current: CurrentUser, db: DbDep) -> list[dict]:
    await get_run_owned(db, run_id, current)
    rows = await db.fetch(
        'SELECT * FROM "DataSeries" WHERE run_id = $1 ORDER BY series_id ASC',
        run_id,
    )
    return [dict(r) for r in rows]


@router.post("/runs/{run_id}/series", response_model=SeriesOut, status_code=status.HTTP_201_CREATED)
async def create_series(run_id: int, data: SeriesIn, current: CurrentUser, db: DbDep) -> dict:
    await get_run_owned(db, run_id, current)
    row = await db.fetchrow(
        """INSERT INTO "DataSeries" (run_id, series_name, unit_x, unit_y, description)
           VALUES ($1, $2, $3, $4, $5) RETURNING *""",
        run_id,
        data.series_name,
        data.unit_x,
        data.unit_y,
        data.description,
    )
    return dict(row)


@router.get("/series/{series_id}", response_model=SeriesOut)
async def get_series(series_id: int, current: CurrentUser, db: DbDep) -> dict:
    return await get_series_owned(db, series_id, current)


@router.patch("/series/{series_id}", response_model=SeriesOut)
async def update_series(series_id: int, data: SeriesIn, current: CurrentUser, db: DbDep) -> dict:
    await get_series_owned(db, series_id, current)
    row = await db.fetchrow(
        """UPDATE "DataSeries"
           SET series_name = $1, unit_x = $2, unit_y = $3, description = $4
           WHERE series_id = $5 RETURNING *""",
        data.series_name,
        data.unit_x,
        data.unit_y,
        data.description,
        series_id,
    )
    return dict(row)


@router.delete("/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_series(series_id: int, current: CurrentUser, db: DbDep) -> None:
    await get_series_owned(db, series_id, current)
    await db.execute('DELETE FROM "DataSeries" WHERE series_id = $1', series_id)


@router.get("/series/{series_id}/points", response_model=list[PointOut])
async def list_points(series_id: int, current: CurrentUser, db: DbDep) -> list[dict]:
    await get_series_owned(db, series_id, current)
    rows = await db.fetch(
        'SELECT * FROM "DataPoints" WHERE series_id = $1 ORDER BY measurement_order ASC',
        series_id,
    )
    return [dict(r) for r in rows]


@router.put("/series/{series_id}/points", response_model=list[PointOut])
async def replace_points(
    series_id: int, data: PointsBulkIn, current: CurrentUser, db: DbDep
) -> list[dict]:
    await get_series_owned(db, series_id, current)
    orders = [p.measurement_order for p in data.points]
    if len(set(orders)) != len(orders):
        raise HTTPException(status_code=422, detail="measurement_order must be unique")
    await db.execute('DELETE FROM "DataPoints" WHERE series_id = $1', series_id)
    if data.points:
        await db.executemany(
            """INSERT INTO "DataPoints"
                   (series_id, measurement_order, x_value, y_value, x_uncertainty, y_uncertainty)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            [
                (
                    series_id,
                    p.measurement_order,
                    p.x_value,
                    p.y_value,
                    p.x_uncertainty,
                    p.y_uncertainty,
                )
                for p in data.points
            ],
        )
    rows = await db.fetch(
        'SELECT * FROM "DataPoints" WHERE series_id = $1 ORDER BY measurement_order ASC',
        series_id,
    )
    return [dict(r) for r in rows]


@router.post(
    "/series/{series_id}/points",
    response_model=PointOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_point(series_id: int, data: PointIn, current: CurrentUser, db: DbDep) -> dict:
    await get_series_owned(db, series_id, current)
    row = await db.fetchrow(
        """INSERT INTO "DataPoints"
               (series_id, measurement_order, x_value, y_value, x_uncertainty, y_uncertainty)
           VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
        series_id,
        data.measurement_order,
        data.x_value,
        data.y_value,
        data.x_uncertainty,
        data.y_uncertainty,
    )
    return dict(row)


@router.delete("/points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_point(point_id: int, current: CurrentUser, db: DbDep) -> None:
    row = await db.fetchrow('SELECT * FROM "DataPoints" WHERE point_id = $1', point_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Point not found")
    await get_series_owned(db, row["series_id"], current)
    await db.execute('DELETE FROM "DataPoints" WHERE point_id = $1', point_id)


# --- plot generation ---


def _render_plot(series: dict, points: list[dict]) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = [p["x_value"] for p in points]
    ys = [p["y_value"] for p in points]
    xerr = [p["x_uncertainty"] or 0.0 for p in points]
    yerr = [p["y_uncertainty"] or 0.0 for p in points]
    ax.errorbar(xs, ys, xerr=xerr, yerr=yerr, fmt="o-", capsize=3)
    ax.set_title(series["series_name"])
    if series["unit_x"]:
        ax.set_xlabel(series["unit_x"])
    if series["unit_y"]:
        ax.set_ylabel(series["unit_y"])
    ax.grid(True, alpha=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


@router.post("/series/{series_id}/plot", response_model=SeriesOut)
async def generate_plot(series_id: int, current: CurrentUser, db: DbDep) -> dict:
    series = await get_series_owned(db, series_id, current)
    rows = await db.fetch(
        'SELECT * FROM "DataPoints" WHERE series_id = $1 ORDER BY measurement_order ASC',
        series_id,
    )
    if not rows:
        raise HTTPException(status_code=422, detail="Series has no data points")

    png = _render_plot(series, [dict(r) for r in rows])

    await db.execute('DELETE FROM "SeriesPlotFile" WHERE series_id = $1', series_id)

    temp_path = f"_uploading/{uuid.uuid4()}.png"
    file_row = await db.fetchrow(
        'INSERT INTO "Files" (mime_type, storage_path, size_bytes) VALUES ($1, $2, $3) RETURNING file_id',
        "image/png",
        temp_path,
        len(png),
    )
    file_id = file_row["file_id"]
    final_path = f"plots/{series_id}/{file_id}.png"
    await db.execute(
        'UPDATE "Files" SET storage_path = $1 WHERE file_id = $2',
        final_path,
        file_id,
    )
    try:
        await upload_bytes(final_path, png, "image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload plot: {str(e)}")
    await db.execute(
        'INSERT INTO "SeriesPlotFile" (series_id, file_id) VALUES ($1, $2)',
        series_id,
        file_id,
    )
    return series
