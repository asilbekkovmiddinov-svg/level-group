from __future__ import annotations

from functools import lru_cache

from app.core import config


class StorageConfigurationError(RuntimeError):
    pass


class StorageOperationError(RuntimeError):
    pass


def validate_storage_config() -> None:
    required = (
        config.S3_ENDPOINT_URL,
        config.S3_ACCESS_KEY_ID,
        config.S3_SECRET_ACCESS_KEY,
        config.S3_BUCKET_NAME,
    )
    if not all(required) or config.S3_PRESIGNED_URL_TTL_SECONDS <= 0:
        raise StorageConfigurationError("Private object storage is not configured")


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
