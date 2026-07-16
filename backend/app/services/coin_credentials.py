import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core import config


def _cipher() -> Fernet:
    if not config.INTERNAL_API_KEY:
        raise RuntimeError("Internal credential encryption is not configured")
    digest = hashlib.sha256(f"level-coin-credentials:{config.INTERNAL_API_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_credential(value: str) -> str:
    return _cipher().encrypt(value.encode()).decode()


def decrypt_credential(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _cipher().decrypt(value.encode()).decode()
    except InvalidToken as error:
        raise RuntimeError("Stored Coin credential cannot be decrypted") from error
