from app.core import config

REQUIRED_PRODUCTION_SETTINGS = (
    "DATABASE_URL", "INTERNAL_API_KEY", "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY", "S3_BUCKET_NAME", "DEPOSIT_CARD_NUMBER",
    "DEPOSIT_CARD_HOLDER", "DEPOSIT_BANK_NAME",
)

def validate_startup_settings() -> None:
    missing = [name for name in REQUIRED_PRODUCTION_SETTINGS if not getattr(config, name, None)]
    if missing:
        raise RuntimeError(f"Missing required production environment variables: {', '.join(missing)}")
