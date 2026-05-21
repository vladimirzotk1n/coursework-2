import asyncio
import logging

import asyncpg

from app.core.config import settings
from app.storage.s3 import delete_object, ensure_bucket

logger = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

POLL_INTERVAL = 2.0
BATCH_SIZE = 20
MAX_RETRIES = 10


async def process_batch(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """
                SELECT id, storage_path FROM "FileDeletionQueue"
                WHERE processed_at IS NULL AND retry_count < $1
                ORDER BY queued_at ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
                """,
                MAX_RETRIES,
                BATCH_SIZE,
            )
            if not rows:
                return 0

            for row in rows:
                try:
                    await delete_object(row["storage_path"])
                    await conn.execute(
                        'UPDATE "FileDeletionQueue"'
                        ' SET processed_at = NOW(), last_error = NULL WHERE id = $1',
                        row["id"],
                    )
                except Exception as e:
                    await conn.execute(
                        """UPDATE "FileDeletionQueue"
                           SET retry_count = retry_count + 1, last_error = $1
                           WHERE id = $2""",
                        str(e)[:500],
                        row["id"],
                    )
                    logger.warning("Delete failed path=%s err=%s", row["storage_path"], e)

            return len(rows)


async def main() -> None:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
    await ensure_bucket()
    logger.info("Worker started")
    try:
        while True:
            try:
                processed = await process_batch(pool)
                if processed == 0:
                    await asyncio.sleep(POLL_INTERVAL)
            except Exception:
                logger.exception("Worker loop error")
                await asyncio.sleep(POLL_INTERVAL)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
