from sqlalchemy import BigInteger, Column, DateTime, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database import Base


class CoinOrderCredential(Base):
    __tablename__ = "coin_order_credentials"
    __table_args__ = (UniqueConstraint("order_type", "order_id", name="uq_coin_credential_order"),)

    id = Column(Integer, primary_key=True)
    order_type = Column(String(10), nullable=False)
    order_id = Column(Integer, nullable=False)
    email_ciphertext = Column(LargeBinary, nullable=False)
    email_nonce = Column(LargeBinary, nullable=False)
    password_ciphertext = Column(LargeBinary, nullable=False)
    password_nonce = Column(LargeBinary, nullable=False)
    key_version = Column(String(20), nullable=False, default="v1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CoinCredentialAccessAudit(Base):
    __tablename__ = "coin_credential_access_audit"

    id = Column(Integer, primary_key=True)
    order_type = Column(String(10), nullable=False)
    order_id = Column(Integer, nullable=False)
    admin_id = Column(BigInteger, nullable=False)
    opened_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip_address = Column(String(64), nullable=True)
    session_id = Column(String(128), nullable=True)
    result = Column(String(20), nullable=False)
