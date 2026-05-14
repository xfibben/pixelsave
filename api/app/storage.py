import time

from minio import Minio
from minio.error import S3Error

from app.config import get_settings


def get_storage_client() -> Minio:
    settings = get_settings()
    return Minio(
        endpoint=settings.storage_endpoint,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        secure=settings.storage_secure,
    )


def ensure_bucket() -> None:
    settings = get_settings()
    client = get_storage_client()
    last_error: Exception | None = None
    for _ in range(10):
        try:
            found = client.bucket_exists(settings.storage_bucket)
            if not found:
                client.make_bucket(settings.storage_bucket)
            return
        except Exception as exc:  # pragma: no cover - container startup retry path
            last_error = exc
            time.sleep(2)
    if last_error is not None:
        raise last_error


def upload_file(file_path: str, object_key: str, content_type: str | None = None) -> int:
    settings = get_settings()
    client = get_storage_client()
    resolved_content_type = content_type or "application/octet-stream"
    client.fput_object(
        bucket_name=settings.storage_bucket,
        object_name=object_key,
        file_path=file_path,
        content_type=resolved_content_type,
    )
    stat = client.stat_object(settings.storage_bucket, object_key)
    return stat.size


def get_object(bucket_name: str, object_key: str):
    client = get_storage_client()
    return client.get_object(bucket_name, object_key)


def delete_object(bucket_name: str, object_key: str) -> None:
    client = get_storage_client()
    try:
        client.remove_object(bucket_name, object_key)
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return
        raise


def object_exists(bucket_name: str, object_key: str) -> bool:
    client = get_storage_client()
    try:
        client.stat_object(bucket_name, object_key)
        return True
    except S3Error as exc:
        if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
            return False
        raise
