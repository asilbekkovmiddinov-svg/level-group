from __future__ import annotations

from functools import lru_cache
from dataclasses import dataclass

from app.core import config


class StorageConfigurationError(RuntimeError):
    pass


class StorageOperationError(RuntimeError):
    pass


class StorageObjectNotFoundError(StorageOperationError):
    pass


@dataclass(frozen=True)
class DownloadedObject:
    content: bytes
    content_type: str
    content_length: int


MAX_RECEIPT_DOWNLOAD_SIZE = 5 * 1024 * 1024
RECEIPT_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


def missing_storage_settings() -> tuple[str, ...]:
    settings = {
        "S3_ENDPOINT_URL": config.S3_ENDPOINT_URL,
        "S3_ACCESS_KEY_ID": config.S3_ACCESS_KEY_ID,
        "S3_SECRET_ACCESS_KEY": config.S3_SECRET_ACCESS_KEY,
        "S3_BUCKET_NAME": config.S3_BUCKET_NAME,
    }
    missing = [name for name, value in settings.items() if not value]
    if config.S3_PRESIGNED_URL_TTL_SECONDS <= 0:
        missing.append("S3_PRESIGNED_URL_TTL_SECONDS")
    return tuple(missing)


def validate_storage_config() -> None:
    missing = missing_storage_settings()
    if missing:
        raise StorageConfigurationError(
            f"Private object storage is not configured; missing: {', '.join(missing)}"
        )


@lru_cache(maxsize=1)
def get_storage_client():
    validate_storage_config()
    try:
        import boto3
        return boto3.client(
            "s3",
            endpoint_url=config.S3_ENDPOINT_URL,
            aws_access_key_id=config.S3_ACCESS_KEY_ID,
            aws_secret_access_key=config.S3_SECRET_ACCESS_KEY,
            region_name=config.S3_REGION,
        )
    except Exception as error:
        raise StorageOperationError("Private object storage is unavailable") from error


def upload_object(object_key: str, content: bytes, content_type: str) -> None:
    try:
        get_storage_client().put_object(
            Bucket=config.S3_BUCKET_NAME,
            Key=object_key,
            Body=content,
            ContentType=content_type,
        )
    except StorageConfigurationError:
        raise
    except Exception as error:
        raise StorageOperationError("Object upload failed") from error


def delete_object(object_key: str) -> None:
    try:
        get_storage_client().delete_object(Bucket=config.S3_BUCKET_NAME, Key=object_key)
    except Exception as error:
        raise StorageOperationError("Object delete failed") from error


def generate_presigned_get_url(object_key: str, expires_in: int | None = None) -> str:
    ttl = expires_in or config.S3_PRESIGNED_URL_TTL_SECONDS
    if ttl <= 0:
        raise StorageConfigurationError("Invalid presigned URL TTL")
    try:
        return get_storage_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": config.S3_BUCKET_NAME, "Key": object_key},
            ExpiresIn=ttl,
        )
    except Exception as error:
        raise StorageOperationError("Presigned URL generation failed") from error


def download_object_bytes(object_key: str) -> DownloadedObject:
    if not object_key:
        raise StorageObjectNotFoundError("Object not found")
    body = None
    try:
        response = get_storage_client().get_object(Bucket=config.S3_BUCKET_NAME, Key=object_key)
        content_type = response.get("ContentType")
        content_length = response.get("ContentLength")
        if content_type not in RECEIPT_CONTENT_TYPES or not isinstance(content_length, int) or content_length < 1 or content_length > MAX_RECEIPT_DOWNLOAD_SIZE:
            raise StorageOperationError("Invalid receipt object")
        body = response["Body"]
        content = body.read(MAX_RECEIPT_DOWNLOAD_SIZE + 1)
        if len(content) != content_length or len(content) > MAX_RECEIPT_DOWNLOAD_SIZE:
            raise StorageOperationError("Invalid receipt object")
        return DownloadedObject(content=content, content_type=content_type, content_length=content_length)
    except StorageOperationError:
        raise
    except Exception as error:
        code = getattr(getattr(error, "response", {}), "get", lambda *_: {})("Error", {}).get("Code")
        if code in {"NoSuchKey", "NoSuchBucket", "404"}:
            raise StorageObjectNotFoundError("Object not found") from error
        raise StorageOperationError("Object download failed") from error
    finally:
        if body is not None:
            try:
                body.close()
            except Exception:
                pass
