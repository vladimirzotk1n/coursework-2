import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentUser, DbDep
from app.core.models import File, RunImage, SeriesPlotFile
from app.features.ownership import get_run_owned, get_series_owned
from app.storage.s3 import presigned_get_url, upload_bytes

router = APIRouter(tags=["files"])


class FileOut(BaseModel):
    file_id: int
    mime_type: str
    storage_path: str
    size_bytes: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}


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
) -> File:
    _require_image(upload)
    await get_run_owned(db, run_id, current)
    data = await upload.read()

    temp_path = f"_uploading/{uuid.uuid4()}"
    file = File(
        mime_type=upload.content_type or "application/octet-stream",
        storage_path=temp_path,
        size_bytes=len(data),
    )
    db.add(file)
    await db.flush()

    ext = (upload.filename or "img").rsplit(".", 1)[-1].lower() if upload.filename else "png"
    final_path = f"images/{run_id}/{file.file_id}.{ext}"
    file.storage_path = final_path
    await db.flush()

    try:
        await upload_bytes(final_path, data, file.mime_type)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to upload image: {str(e)}")

    db.add(RunImage(file_id=file.file_id, run_id=run_id))
    await db.flush()
    return file


@router.get("/runs/{run_id}/images", response_model=list[FileWithUrl])
async def list_run_images(run_id: int, current: CurrentUser, db: DbDep) -> list[FileWithUrl]:
    await get_run_owned(db, run_id, current)
    stmt = (
        select(File)
        .join(RunImage, RunImage.file_id == File.file_id)
        .where(RunImage.run_id == run_id)
        .order_by(File.uploaded_at.desc())
    )
    files = list((await db.scalars(stmt)).all())
    return [
        FileWithUrl(**FileOut.model_validate(f).model_dump(), url=await presigned_get_url(f.storage_path))
        for f in files
    ]


@router.delete("/runs/{run_id}/images/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run_image(
    run_id: int, file_id: int, current: CurrentUser, db: DbDep
) -> None:
    await get_run_owned(db, run_id, current)
    link = await db.scalar(
        select(RunImage).where(RunImage.file_id == file_id, RunImage.run_id == run_id)
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Image not found")
    await db.delete(link)


@router.get("/series/{series_id}/plot", response_model=FileWithUrl | None)
async def get_series_plot(series_id: int, current: CurrentUser, db: DbDep) -> FileWithUrl | None:
    await get_series_owned(db, series_id, current)
    stmt = (
        select(File)
        .join(SeriesPlotFile, SeriesPlotFile.file_id == File.file_id)
        .where(SeriesPlotFile.series_id == series_id)
    )
    file = await db.scalar(stmt)
    if file is None:
        return None
    return FileWithUrl(
        **FileOut.model_validate(file).model_dump(),
        url=await presigned_get_url(file.storage_path),
    )
