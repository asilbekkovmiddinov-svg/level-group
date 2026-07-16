import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.coin_credential import CoinCredentialAccessAudit, CoinCredentialAccessGrant, CoinOrderCredential
from app.models.coin_order_message import CoinOrderMessage
from app.services.coin_credentials import decrypt_value, encrypt_value


def store_credentials(db: Session, order_type: str, order_id: int, email: str, password: str):
    email_ciphertext, email_nonce = encrypt_value(email, order_type=order_type, order_id=order_id, field="EMAIL")
    password_ciphertext, password_nonce = encrypt_value(password, order_type=order_type, order_id=order_id, field="PASSWORD")
    item = CoinOrderCredential(
        order_type=order_type, order_id=order_id,
        email_ciphertext=email_ciphertext, email_nonce=email_nonce,
        password_ciphertext=password_ciphertext, password_nonce=password_nonce,
    )
    db.add(item)
    return item


def open_credentials(db: Session, order_type: str, order_id: int, admin_id: int, ip_address=None, session_id=None):
    item = db.query(CoinOrderCredential).filter_by(order_type=order_type, order_id=order_id).first()
    if not item:
        db.add(CoinCredentialAccessAudit(order_type=order_type, order_id=order_id, admin_id=admin_id,
            ip_address=ip_address, session_id=session_id, result="MISSING"))
        db.commit()
        return None
    try:
        result = {
            "email": decrypt_value(item.email_ciphertext, item.email_nonce, order_type=order_type, order_id=order_id, field="EMAIL"),
            "password": decrypt_value(item.password_ciphertext, item.password_nonce, order_type=order_type, order_id=order_id, field="PASSWORD"),
        }
        audit_result = "OPENED"
    except Exception:
        result = None
        audit_result = "FAILED"
    db.add(CoinCredentialAccessAudit(order_type=order_type, order_id=order_id, admin_id=admin_id,
        ip_address=ip_address, session_id=session_id, result=audit_result))
    db.commit()
    return result


def cleanup_sensitive_order_data(db: Session, order_type: str, order_id: int):
    db.query(CoinOrderCredential).filter_by(order_type=order_type, order_id=order_id).delete(synchronize_session=False)
    for message in db.query(CoinOrderMessage).filter_by(order_type=order_type, order_id=order_id, sender="USER").all():
        value = message.message.strip()
        if len(value) == 6 and value.isdigit():
            message.message = "OTP qabul qilindi"
    db.flush()


def create_access_grant(db: Session, order_type: str, order_id: int, admin_id: int):
    token = secrets.token_urlsafe(32)
    db.add(CoinCredentialAccessGrant(
        token_hash=hashlib.sha256(token.encode()).hexdigest(), order_type=order_type,
        order_id=order_id, admin_id=admin_id,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    ))
    db.commit()
    return token


def consume_access_grant(db: Session, token: str, admin_id: int):
    item = db.query(CoinCredentialAccessGrant).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).with_for_update().first()
    now = datetime.now(timezone.utc)
    if not item or item.used_at is not None or item.admin_id != admin_id:
        return None
    expires = item.expires_at if item.expires_at.tzinfo else item.expires_at.replace(tzinfo=timezone.utc)
    if expires <= now:
        return None
    item.used_at = now
    db.commit()
    return item
