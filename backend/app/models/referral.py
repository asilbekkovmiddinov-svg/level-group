from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class ReferralProfile(Base):
    __tablename__ = "referral_profiles"

    telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        primary_key=True,
    )
    referral_code = Column(String(24), nullable=False, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (
        UniqueConstraint("referred_telegram_id", name="uq_referrals_referred_user"),
        CheckConstraint(
            "referrer_telegram_id <> referred_telegram_id",
            name="ck_referrals_not_self",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    referrer_telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )
    referred_telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
    )
    status = Column(String(20), nullable=False, default="ACTIVE")
    linked_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoke_reason = Column(String(255), nullable=True)


class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    __table_args__ = (
        UniqueConstraint(
            "referral_id",
            "reward_type",
            name="uq_referral_reward_type",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    referral_id = Column(
        Integer,
        ForeignKey("referrals.id"),
        nullable=False,
        index=True,
    )
    beneficiary_telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        nullable=False,
        index=True,
    )
    reward_type = Column(String(40), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=False,
        unique=True,
    )
    status = Column(String(20), nullable=False, default="AWARDED")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)
