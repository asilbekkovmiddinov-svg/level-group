import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core import config


def _key() -> bytes:
    try:
        key = base64.urlsafe_b64decode(config.COIN_CREDENTIAL_ENCRYPTION_KEY)
    except Exception as exc:
        raise RuntimeError("Coin credential encryption key is invalid") from exc
    if len(key) != 32:
        raise RuntimeError("Coin credential encryption key must contain 32 bytes")
    return key


def encrypt_value(value: str, *, order_type: str, order_id: int, field: str):
    nonce = os.urandom(12)
    aad = f"{order_type}:{order_id}:{field}:v1".encode()
    return AESGCM(_key()).encrypt(nonce, value.encode(), aad), nonce


def decrypt_value(ciphertext: bytes, nonce: bytes, *, order_type: str, order_id: int, field: str):
    aad = f"{order_type}:{order_id}:{field}:v1".encode()
    return AESGCM(_key()).decrypt(nonce, ciphertext, aad).decode()


def credential_fingerprint(email: str, password: str) -> str:
    """Create a stable, non-reversible idempotency digest for credentials."""
    payload = f"{email.strip().lower()}\0{password}".encode()
    return hmac.new(_key(), payload, hashlib.sha256).hexdigest()
