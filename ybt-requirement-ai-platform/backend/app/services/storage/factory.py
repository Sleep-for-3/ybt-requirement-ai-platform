from functools import lru_cache

from app.core.settings import get_settings
from app.services.storage.local import LocalStorageService
from app.services.storage.s3 import S3CompatibleStorageService


@lru_cache
def get_storage_service():
    settings = get_settings()
    if settings.storage_provider == "s3":
        import boto3
        client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None, region_name=settings.s3_region)
        return S3CompatibleStorageService(client, settings.s3_bucket_name)
    return LocalStorageService(settings.storage_dir)
