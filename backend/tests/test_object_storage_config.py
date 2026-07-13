import pytest

from app.services import object_storage


def test_missing_storage_settings_are_named_without_secret_values(monkeypatch):
    monkeypatch.setattr(object_storage.config, "S3_ENDPOINT_URL", None)
    monkeypatch.setattr(object_storage.config, "S3_ACCESS_KEY_ID", "")
    monkeypatch.setattr(object_storage.config, "S3_SECRET_ACCESS_KEY", "secret-value")
    monkeypatch.setattr(object_storage.config, "S3_BUCKET_NAME", None)
    monkeypatch.setattr(object_storage.config, "S3_PRESIGNED_URL_TTL_SECONDS", 300)

    assert object_storage.missing_storage_settings() == (
        "S3_ENDPOINT_URL",
        "S3_ACCESS_KEY_ID",
        "S3_BUCKET_NAME",
    )

    with pytest.raises(object_storage.StorageConfigurationError) as error:
        object_storage.validate_storage_config()

    message = str(error.value)
    assert "S3_ENDPOINT_URL" in message
    assert "S3_ACCESS_KEY_ID" in message
    assert "S3_BUCKET_NAME" in message
    assert "secret-value" not in message


def test_upload_preserves_configuration_error(monkeypatch):
    object_storage.get_storage_client.cache_clear()
    monkeypatch.setattr(object_storage.config, "S3_ENDPOINT_URL", None)
    monkeypatch.setattr(object_storage.config, "S3_ACCESS_KEY_ID", None)
    monkeypatch.setattr(object_storage.config, "S3_SECRET_ACCESS_KEY", None)
    monkeypatch.setattr(object_storage.config, "S3_BUCKET_NAME", None)

    with pytest.raises(object_storage.StorageConfigurationError):
        object_storage.upload_object("receipt.jpg", b"content", "image/jpeg")

    object_storage.get_storage_client.cache_clear()
