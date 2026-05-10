import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import CurrentUser, DbDep
from app.core.models import (
    File,
    Report,
    ReportAttachment,
    ReportPdfFile,
    ReportSourceFile,
)
from app.features.ownership import get_report_owned, get_run_owned
from app.storage.s3 import presigned_get_url, upload_bytes

router = APIRouter(tags=["reports"])


class ReportIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ReportOut(BaseModel):
    report_id: int
    run_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReportFileOut(BaseModel):
    file_id: int
    mime_type: str
    size_bytes: int
    url: str


@router.get("/runs/{run_id}/reports", response_model=list[ReportOut])
async def list_reports(run_id: int, current: CurrentUser, db: DbDep) -> list[Report]:
    await get_run_owned(db, run_id, current)
    stmt = select(Report).where(Report.run_id == run_id).order_by(Report.created_at.desc())
    return list((await db.scalars(stmt)).all())


@router.post(
    "/runs/{run_id}/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    run_id: int, data: ReportIn, current: CurrentUser, db: DbDep
) -> Report:
    await get_run_owned(db, run_id, current)
    report = Report(run_id=run_id, title=data.title)
    db.add(report)
    await db.flush()
    return report


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: int, current: CurrentUser, db: DbDep) -> Report:
    return await get_report_owned(db, report_id, current)


@router.patch("/reports/{report_id}", response_model=ReportOut)
async def update_report(
    report_id: int, data: ReportIn, current: CurrentUser, db: DbDep
) -> Report:
    report = await get_report_owned(db, report_id, current)
    report.title = data.title
    await db.flush()
    return report


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: int, current: CurrentUser, db: DbDep) -> None:
    report = await get_report_owned(db, report_id, current)
    await db.delete(report)


async def _replace_single_file(
    db,
    report_id: int,
    junction_cls,
    existing_stmt,
    key: str,
    content: bytes,
    mime: str,
) -> File:
    existing = await db.scalar(existing_stmt)
    if existing is not None:
        await db.delete(existing)
        await db.flush()
    temp_path = f"_uploading/{uuid.uuid4()}"
    file = File(mime_type=mime, storage_path=temp_path, size_bytes=len(content))
    db.add(file)
    await db.flush()
    file.storage_path = key
    await db.flush()
    try:
        await upload_bytes(key, content, mime)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    db.add(junction_cls(report_id=report_id, file_id=file.file_id))
    await db.flush()
    return file


@router.put("/reports/{report_id}/source", response_model=ReportFileOut)
async def upload_source(
    report_id: int, upload: UploadFile, current: CurrentUser, db: DbDep
) -> ReportFileOut:
    await get_report_owned(db, report_id, current)
    content = await upload.read()
    file = await _replace_single_file(
        db,
        report_id,
        ReportSourceFile,
        select(ReportSourceFile).where(ReportSourceFile.report_id == report_id),
        key=f"reports/{report_id}/report.tex",
        content=content,
        mime=upload.content_type or "application/x-tex",
    )
    return ReportFileOut(
        file_id=file.file_id,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        url=await presigned_get_url(file.storage_path),
    )


@router.put("/reports/{report_id}/pdf", response_model=ReportFileOut)
async def upload_pdf(
    report_id: int, upload: UploadFile, current: CurrentUser, db: DbDep
) -> ReportFileOut:
    await get_report_owned(db, report_id, current)
    content = await upload.read()
    file = await _replace_single_file(
        db,
        report_id,
        ReportPdfFile,
        select(ReportPdfFile).where(ReportPdfFile.report_id == report_id),
        key=f"reports/{report_id}/report.pdf",
        content=content,
        mime=upload.content_type or "application/pdf",
    )
    return ReportFileOut(
        file_id=file.file_id,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        url=await presigned_get_url(file.storage_path),
    )


@router.post(
    "/reports/{report_id}/attachments",
    response_model=ReportFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_attachment(
    report_id: int, upload: UploadFile, current: CurrentUser, db: DbDep
) -> ReportFileOut:
    await get_report_owned(db, report_id, current)
    content = await upload.read()
    mime = upload.content_type or "application/octet-stream"

    temp_path = f"_uploading/{uuid.uuid4()}"
    file = File(mime_type=mime, storage_path=temp_path, size_bytes=len(content))
    db.add(file)
    await db.flush()
    ext = (upload.filename or "bin").rsplit(".", 1)[-1].lower() if upload.filename else "bin"
    final_path = f"reports/{report_id}/{file.file_id}.{ext}"
    file.storage_path = final_path
    await db.flush()
    try:
        await upload_bytes(final_path, content, mime)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to upload attachment: {str(e)}")
    db.add(ReportAttachment(file_id=file.file_id, report_id=report_id))
    await db.flush()
    return ReportFileOut(
        file_id=file.file_id,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        url=await presigned_get_url(file.storage_path),
    )


@router.get("/reports/{report_id}/attachments", response_model=list[ReportFileOut])
async def list_attachments(
    report_id: int, current: CurrentUser, db: DbDep
) -> list[ReportFileOut]:
    await get_report_owned(db, report_id, current)
    stmt = (
        select(File)
        .join(ReportAttachment, ReportAttachment.file_id == File.file_id)
        .where(ReportAttachment.report_id == report_id)
    )
    files = list((await db.scalars(stmt)).all())
    return [
        ReportFileOut(
            file_id=f.file_id,
            mime_type=f.mime_type,
            size_bytes=f.size_bytes,
            url=await presigned_get_url(f.storage_path),
        )
        for f in files
    ]


@router.delete(
    "/reports/{report_id}/attachments/{file_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_attachment(
    report_id: int, file_id: int, current: CurrentUser, db: DbDep
) -> None:
    await get_report_owned(db, report_id, current)
    link = await db.scalar(
        select(ReportAttachment).where(
            ReportAttachment.report_id == report_id, ReportAttachment.file_id == file_id
        )
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    await db.delete(link)


@router.get("/reports/{report_id}/source", response_model=ReportFileOut | None)
async def get_source(
    report_id: int, current: CurrentUser, db: DbDep
) -> ReportFileOut | None:
    await get_report_owned(db, report_id, current)
    stmt = (
        select(File)
        .join(ReportSourceFile, ReportSourceFile.file_id == File.file_id)
        .where(ReportSourceFile.report_id == report_id)
    )
    file = await db.scalar(stmt)
    if file is None:
        return None
    return ReportFileOut(
        file_id=file.file_id,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        url=await presigned_get_url(file.storage_path),
    )


@router.get("/reports/{report_id}/pdf", response_model=ReportFileOut | None)
async def get_pdf(report_id: int, current: CurrentUser, db: DbDep) -> ReportFileOut | None:
    await get_report_owned(db, report_id, current)
    stmt = (
        select(File)
        .join(ReportPdfFile, ReportPdfFile.file_id == File.file_id)
        .where(ReportPdfFile.report_id == report_id)
    )
    file = await db.scalar(stmt)
    if file is None:
        return None
    return ReportFileOut(
        file_id=file.file_id,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        url=await presigned_get_url(file.storage_path),
    )
