import io
from functools import lru_cache

from minio import Minio
from minio.commonconfig import Tags

from app.settings import Settings


@lru_cache
def _client(endpoint: str, access_key: str, secret_key: str, secure: bool) -> Minio:
    return Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)


def get_client(settings: Settings) -> Minio:
    return _client(
        settings.minio_endpoint, settings.minio_access_key, settings.minio_secret_key, settings.minio_secure
    )


def ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def object_key(knowledge_id: int, filename: str) -> str:
    return f"knowledge/{knowledge_id}/{filename}"


def upload(client: Minio, bucket: str, key: str, content: bytes) -> None:
    ensure_bucket(client, bucket)
    client.put_object(bucket, key, io.BytesIO(content), length=len(content))


def archive(client: Minio, bucket: str, key: str) -> None:
    tags = Tags.new_object_tags()
    tags["archived"] = "true"
    client.set_object_tags(bucket, key, tags)


def delete_if_exists(client: Minio, bucket: str, key: str) -> None:
    try:
        client.remove_object(bucket, key)
    except Exception:
        pass
