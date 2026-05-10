from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session

from app.core.config import settings

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = get_session()
    return _session


@asynccontextmanager
async def s3_client() -> AsyncIterator:
    config = AioConfig(
        max_pool_connections=10,
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 3, "mode": "standard"},
    )
    session = _get_session()
    async with session.create_client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=config,
    ) as client:
        yield client


async def ensure_bucket() -> None:
    async with s3_client() as client:
        try:
            await client.head_bucket(Bucket=settings.s3_bucket)
        except Exception as e:
            try:
                await client.create_bucket(Bucket=settings.s3_bucket)
            except Exception as create_error:
                print(f"Failed to create bucket: {create_error}")
                raise


async def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    async with s3_client() as client:
        try:
            await client.put_object(
                Bucket=settings.s3_bucket, Key=key, Body=data, ContentType=content_type
            )
        except Exception as e:
            raise RuntimeError(f"Failed to upload file to S3: {e}")


async def download_bytes(key: str) -> bytes:
    async with s3_client() as client:
        try:
            resp = await client.get_object(Bucket=settings.s3_bucket, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()
        except Exception as e:
            raise RuntimeError(f"Failed to download file from S3: {e}")


async def delete_object(key: str) -> None:
    async with s3_client() as client:
        try:
            await client.delete_object(Bucket=settings.s3_bucket, Key=key)
        except Exception as e:
            raise RuntimeError(f"Failed to delete file from S3: {e}")


async def presigned_get_url(key: str, expires: int = 3600) -> str:
    async with s3_client() as client:
        try:
            url = await client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket, "Key": key},
                ExpiresIn=expires,
            )
            url = url.replace(settings.s3_endpoint_url, settings.s3_public_endpoint_url)
            return url
        except Exception as e:
            raise RuntimeError(f"Failed to generate presigned URL: {e}")
