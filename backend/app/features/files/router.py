import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.core.deps import CurrentUser, DbDep
from app.features.ownership import get_run_owned, get_series_owned
from app.storage.s3 import presigned_get_url, upload_bytes

router = APIRouter(tags=["files"])


class FileOut(BaseModel):
    file_id: int
    mime_type: str
    storage_path: str
    size_bytes: int
    uploaded_at: datetime


class FileWithUrl(FileOut):
    url: str


def _require_image(upload: UploadFile) -> None:
    if not upload.content_type or not upload.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Only image uploads are accepted here")


@router.post(
    "/runs/{run_id}/images",
    response_model=FileOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_run_image(
    run_id: int, upload: UploadFile, current: CurrentUser, db: DbDep
) -> dict:
    _require_image(upload)
    await get_run_owned(db, run_id, current)
    data = await upload.read()
    mime = upload.content_type or "application/octet-stream"

    temp_path = f"_uploading/{uuid.uuid4()}"
    file_row = await db.fetchrow(
        'INSERT INTO "Files" (mime_type, storage_path, size_bytes) VALUES ($1, $2, $3) RETURNING *',
        mime,
        temp_path,
        len(data),
    )
    file_id = file_row["file_id"]
    ext = (upload.filename or "img").rsplit(".", 1)[-1].lower() if upload.filename else "png"
    final_path = f"images/{run_id}/{file_id}.{ext}"
    await db.execute(
        'UPDATE "Files" SET storage_path = $1 WHERE file_id = $2',
        final_path,
        file_id,
    )
    try:
        await upload_bytes(final_path, data, mime)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")
    await db.execute(
        'INSERT INTO "RunImages" (file_id, run_id) VALUES ($1, $2)',
        file_id,
        run_id,
    )
    row = await db.fetchrow('SELECT * FROM "Files" WHERE file_id = $1', file_id)
    return dict(row)


@router.get("/runs/{run_id}/images", response_model=list[FileWithUrl])
async def list_run_images(run_id: int, current: CurrentUser, db: DbDep) -> list[dict]:
    await get_run_owned(db, run_id, current)
    rows = await db.fetch(
        """SELECT f.* FROM "Files" f
             JOIN "RunImages" ri ON ri.file_id = f.file_id
           WHERE ri.run_id = $1
           ORDER BY f.uploaded_at DESC""",
        run_id,
    )
    result = []
    for r in rows:
        d = dict(r)
        d["url"] = await presigned_get_url(d["storage_path"])
        result.append(d)
    return result


@router.delete("/runs/{run_id}/images/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run_image(
    run_id: int, file_id: int, current: CurrentUser, db: DbDep
) -> None:
    await get_run_owned(db, run_id, current)
    result = await db.execute(
        'DELETE FROM "RunImages" WHERE file_id = $1 AND run_id = $2',
        file_id,
        run_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Image not found")


@router.get("/series/{series_id}/plot", response_model=FileWithUrl | None)
async def get_series_plot(series_id: int, current: CurrentUser, db: DbDep) -> dict | None:
    await get_series_owned(db, series_id, current)
    row = await db.fetchrow(
        """SELECT f.* FROM "Files" f
             JOIN "SeriesPlotFile" sp ON sp.file_id = f.file_id
           WHERE sp.series_id = $1""",
        series_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["url"] = await presigned_get_url(d["storage_path"])
    return d
