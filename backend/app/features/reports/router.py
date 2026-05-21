import uuid
from datetime import datetime

import asyncpg
from fastapi import APIRouter, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.core.deps import CurrentUser, DbDep
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


class ReportFileOut(BaseModel):
    file_id: int
    mime_type: str
    size_bytes: int
    url: str


@router.get("/runs/{run_id}/reports", response_model=list[ReportOut])
async def list_reports(run_id: int, current: CurrentUser, db: DbDep) -> list[dict]:
    await get_run_owned(db, run_id, current)
    rows = await db.fetch(
        'SELECT * FROM "Reports" WHERE run_id = $1 ORDER BY created_at DESC',
        run_id,
    )
    return [dict(r) for r in rows]


@router.post(
    "/runs/{run_id}/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(run_id: int, data: ReportIn, current: CurrentUser, db: DbDep) -> dict:
    await get_run_owned(db, run_id, current)
    row = await db.fetchrow(
        'INSERT INTO "Reports" (run_id, title) VALUES ($1, $2) RETURNING *',
        run_id,
        data.title,
    )
    return dict(row)


@router.get("/reports/{report_id}", response_model=ReportOut)
async def get_report(report_id: int, current: CurrentUser, db: DbDep) -> dict:
    return await get_report_owned(db, report_id, current)


@router.patch("/reports/{report_id}", response_model=ReportOut)
async def update_report(
    report_id: int, data: ReportIn, current: CurrentUser, db: DbDep
) -> dict:
    await get_report_owned(db, report_id, current)
    row = await db.fetchrow(
        'UPDATE "Reports" SET title = $1 WHERE report_id = $2 RETURNING *',
        data.title,
        report_id,
    )
    return dict(row)


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: int, current: CurrentUser, db: DbDep) -> None:
    await get_report_owned(db, report_id, current)
    await db.execute('DELETE FROM "Reports" WHERE report_id = $1', report_id)


async def _replace_single_file(
    db: asyncpg.Connection,
    report_id: int,
    junction_table: str,
    key: str,
    content: bytes,
    mime: str,
) -> dict:
    """Replace the 1:1 file linked to a report (source or PDF)."""
    await db.execute(f'DELETE FROM "{junction_table}" WHERE report_id = $1', report_id)

    temp_path = f"_uploading/{uuid.uuid4()}"
    file_row = await db.fetchrow(
        'INSERT INTO "Files" (mime_type, storage_path, size_bytes) VALUES ($1, $2, $3) RETURNING file_id',
        mime,
        temp_path,
        len(content),
    )
    file_id = file_row["file_id"]
    await db.execute('UPDATE "Files" SET storage_path = $1 WHERE file_id = $2', key, file_id)
    try:
        await upload_bytes(key, content, mime)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")
    await db.execute(
        f'INSERT INTO "{junction_table}" (report_id, file_id) VALUES ($1, $2)',
        report_id,
        file_id,
    )
    url = await presigned_get_url(key)
    return {"file_id": file_id, "mime_type": mime, "size_bytes": len(content), "url": url}


@router.put("/reports/{report_id}/source", response_model=ReportFileOut)
async def upload_source(
    report_id: int, upload: UploadFile, current: CurrentUser, db: DbDep
) -> dict:
    await get_report_owned(db, report_id, current)
    content = await upload.read()
    return await _replace_single_file(
        db,
        report_id,
        "ReportSourceFile",
        key=f"reports/{report_id}/report.tex",
        content=content,
        mime=upload.content_type or "application/x-tex",
    )


@router.put("/reports/{report_id}/pdf", response_model=ReportFileOut)
async def upload_pdf(
    report_id: int, upload: UploadFile, current: CurrentUser, db: DbDep
) -> dict:
    await get_report_owned(db, report_id, current)
    content = await upload.read()
    return await _replace_single_file(
        db,
        report_id,
        "ReportPdfFile",
        key=f"reports/{report_id}/report.pdf",
        content=content,
        mime=upload.content_type or "application/pdf",
    )


@router.post(
    "/reports/{report_id}/attachments",
    response_model=ReportFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_attachment(
    report_id: int, upload: UploadFile, current: CurrentUser, db: DbDep
) -> dict:
    await get_report_owned(db, report_id, current)
    content = await upload.read()
    mime = upload.content_type or "application/octet-stream"

    temp_path = f"_uploading/{uuid.uuid4()}"
    file_row = await db.fetchrow(
        'INSERT INTO "Files" (mime_type, storage_path, size_bytes) VALUES ($1, $2, $3) RETURNING file_id',
        mime,
        temp_path,
        len(content),
    )
    file_id = file_row["file_id"]
    ext = (upload.filename or "bin").rsplit(".", 1)[-1].lower() if upload.filename else "bin"
    final_path = f"reports/{report_id}/{file_id}.{ext}"
    await db.execute('UPDATE "Files" SET storage_path = $1 WHERE file_id = $2', final_path, file_id)
    try:
        await upload_bytes(final_path, content, mime)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload attachment: {str(e)}")
    await db.execute(
        'INSERT INTO "ReportAttachments" (file_id, report_id) VALUES ($1, $2)',
        file_id,
        report_id,
    )
    url = await presigned_get_url(final_path)
    return {"file_id": file_id, "mime_type": mime, "size_bytes": len(content), "url": url}


@router.get("/reports/{report_id}/attachments", response_model=list[ReportFileOut])
async def list_attachments(
    report_id: int, current: CurrentUser, db: DbDep
) -> list[dict]:
    await get_report_owned(db, report_id, current)
    rows = await db.fetch(
        """SELECT f.* FROM "Files" f
             JOIN "ReportAttachments" ra ON ra.file_id = f.file_id
           WHERE ra.report_id = $1""",
        report_id,
    )
    result = []
    for r in rows:
        d = dict(r)
        result.append({
            "file_id": d["file_id"],
            "mime_type": d["mime_type"],
            "size_bytes": d["size_bytes"],
            "url": await presigned_get_url(d["storage_path"]),
        })
    return result


@router.delete(
    "/reports/{report_id}/attachments/{file_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_attachment(
    report_id: int, file_id: int, current: CurrentUser, db: DbDep
) -> None:
    await get_report_owned(db, report_id, current)
    result = await db.execute(
        'DELETE FROM "ReportAttachments" WHERE report_id = $1 AND file_id = $2',
        report_id,
        file_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Attachment not found")


@router.get("/reports/{report_id}/source", response_model=ReportFileOut | None)
async def get_source(report_id: int, current: CurrentUser, db: DbDep) -> dict | None:
    await get_report_owned(db, report_id, current)
    row = await db.fetchrow(
        """SELECT f.* FROM "Files" f
             JOIN "ReportSourceFile" rs ON rs.file_id = f.file_id
           WHERE rs.report_id = $1""",
        report_id,
    )
    if row is None:
        return None
    d = dict(row)
    return {
        "file_id": d["file_id"],
        "mime_type": d["mime_type"],
        "size_bytes": d["size_bytes"],
        "url": await presigned_get_url(d["storage_path"]),
    }


@router.get("/reports/{report_id}/pdf", response_model=ReportFileOut | None)
async def get_pdf(report_id: int, current: CurrentUser, db: DbDep) -> dict | None:
    await get_report_owned(db, report_id, current)
    row = await db.fetchrow(
        """SELECT f.* FROM "Files" f
             JOIN "ReportPdfFile" rp ON rp.file_id = f.file_id
           WHERE rp.report_id = $1""",
        report_id,
    )
    if row is None:
        return None
    d = dict(row)
    return {
        "file_id": d["file_id"],
        "mime_type": d["mime_type"],
        "size_bytes": d["size_bytes"],
        "url": await presigned_get_url(d["storage_path"]),
    }
