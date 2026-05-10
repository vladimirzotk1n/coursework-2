import asyncio
import logging

from sqlalchemy import func, select, update

from app.core.db import SessionLocal
from app.core.models import FileDeletionQueue
from app.storage.s3 import delete_object, ensure_bucket

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

POLL_INTERVAL = 2.0
BATCH_SIZE = 20
MAX_RETRIES = 10


async def process_batch() -> int:
    async with SessionLocal() as session:
        stmt = (
            select(FileDeletionQueue)
            .where(
                FileDeletionQueue.processed_at.is_(None),
                FileDeletionQueue.retry_count < MAX_RETRIES,
            )
            .order_by(FileDeletionQueue.queued_at.asc())
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        rows = list((await session.scalars(stmt)).all())
        if not rows:
            await session.commit()
            return 0

        for row in rows:
            try:
                await delete_object(row.storage_path)
                row.processed_at = func.now()
                row.last_error = None
            except Exception as e:
                row.retry_count += 1
                row.last_error = str(e)[:500]
                logger.warning("Delete failed path=%s err=%s", row.storage_path, e)
        await session.commit()
        return len(rows)


async def main() -> None:
    await ensure_bucket()
    logger.info("Worker started")
    while True:
        try:
            processed = await process_batch()
            if processed == 0:
                await asyncio.sleep(POLL_INTERVAL)
        except Exception:
            logger.exception("Worker loop error")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
