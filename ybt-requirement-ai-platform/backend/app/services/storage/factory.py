from functools import lru_cache

from app.core.settings import Settings
from app.services.storage.local import LocalStorageService
from app.services.storage.s3 import S3CompatibleStorageService


@lru_cache
def get_storage_service():
    # The service itself remains cached.  Constructing Settings here ensures
    # an explicit cache_clear (used by tests and runtime reconfiguration)
    # observes the current environment instead of a stale application-level
    # settings object.
    settings = Settings()
    if settings.storage_provider == "s3":
        import boto3
        client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None, region_name=settings.s3_region)
        return S3CompatibleStorageService(client, settings.s3_bucket_name)
    return LocalStorageService(settings.storage_dir)
