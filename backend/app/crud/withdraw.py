from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.crud.transaction import create_transaction
from app.crud.wallet import (
    confirm_locked_uzs,
    get_wallet_for_update,
    lock_uzs_balance,
    to_decimal,
    unlock_uzs_balance,
)
from app.models.withdraw import Withdraw
from app.schemas.withdraw import WithdrawCreate
MIN_WITHDRAW_AMOUNT = Decimal("15000")
def _withdraw_for_update(db: Session, withdraw_id: int):
    return db.query(Withdraw).filter(Withdraw.id == withdraw_id).with_for_update().first()
def _processing_seconds(created_at, now: datetime) -> int:
    if not created_at:
        return 0
    if created_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return max(0, int((now - created_at).total_seconds()))
def create_withdraw(db: Session, data: WithdrawCreate, telegram_id: int):
    amount = to_decimal(data.amount)
    if amount is None:
        return "invalid_amount"
    if amount < MIN_WITHDRAW_AMOUNT:
        return "minimum_amount"

    try:
        with db.begin():
            wallet = get_wallet_for_update(db, telegram_id)
            if not wallet:
                return "wallet_not_found"
            if Decimal(str(wallet.uzs_balance)) < amount:
                return "insufficient"

            locked_wallet = lock_uzs_balance(db, telegram_id, amount)
            if not locked_wallet:
                return "insufficient"

            withdraw = Withdraw(
                telegram_id=telegram_id,
                amount=amount,
                card_number=data.card_number,
                card_holder=data.card_holder,
                bank_name=data.bank_name,
                status="PENDING",
            )
            db.add(withdraw)
            db.flush()

            balance_after = Decimal(str(locked_wallet.uzs_balance))
            create_transaction(
                db=db,
                telegram_id=telegram_id,
                currency="UZS",
                amount=amount,
                balance_before=balance_after + amount,
                balance_after=balance_after,
                type="WITHDRAW_REQUEST",
                description="Pul yechish so‘rovi yaratildi. Muddat: 24 soatgacha.",
                commit=False,
            )
            return withdraw
    except SQLAlchemyError:
        return "operation_failed"
def claim_withdraw(db: Session, withdraw_id: int, admin_id: int):
    try:
        with db.begin():
            withdraw = _withdraw_for_update(db, withdraw_id)
            if not withdraw:
                return None
            if withdraw.status == "CLAIMED":
                return "already_claimed"
            if withdraw.status != "PENDING":
                return "not_pending"

            withdraw.status = "CLAIMED"
            withdraw.claimed_by = admin_id
            withdraw.claimed_at = datetime.now(timezone.utc)
            db.flush()
            return withdraw
    except SQLAlchemyError:
        return "operation_failed"
def approve_withdraw(db: Session, withdraw_id: int, admin_id: int):
    try:
        with db.begin():
            withdraw = _withdraw_for_update(db, withdraw_id)
            if not withdraw:
                return None
            if withdraw.status == "APPROVED":
                return "approved"
            if withdraw.status == "REJECTED":
                return "rejected"
            if withdraw.status != "CLAIMED":
                return "not_claimed"
            if withdraw.claimed_by != admin_id:
                return "not_owner"

            amount = to_decimal(withdraw.amount)
            if amount is None:
                return "invalid_amount"
            wallet = get_wallet_for_update(db, withdraw.telegram_id)
            if not wallet:
                return "locked"

            balance_before = Decimal(str(wallet.uzs_balance))
            if Decimal(str(wallet.locked_uzs)) < amount:
                return "locked"
            if not confirm_locked_uzs(db, withdraw.telegram_id, amount):
                return "locked"

            now = datetime.now(timezone.utc)
            withdraw.status = "APPROVED"
            withdraw.approved_by = admin_id
            withdraw.approved_at = now
            withdraw.processing_seconds = _processing_seconds(withdraw.created_at, now)
            create_transaction(
                db=db,
                telegram_id=withdraw.telegram_id,
                currency="UZS",
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_before,
                type="WITHDRAW_APPROVED",
                description="Pul yechish admin tomonidan tasdiqlandi.",
                commit=False,
            )
            db.flush()
            return withdraw
    except SQLAlchemyError:
        return "operation_failed"
def reject_withdraw(
    db: Session,
    withdraw_id: int,
    admin_id: int,
    reason: str = "Admin rad etdi",
):
    try:
        with db.begin():
            withdraw = _withdraw_for_update(db, withdraw_id)
            if not withdraw:
                return None
            if withdraw.status == "APPROVED":
                return "approved"
            if withdraw.status == "REJECTED":
                return "rejected"
            if withdraw.status != "CLAIMED":
                return "not_claimed"
            if withdraw.claimed_by != admin_id:
                return "not_owner"

            amount = to_decimal(withdraw.amount)
            if amount is None:
                return "invalid_amount"
            wallet = get_wallet_for_update(db, withdraw.telegram_id)
            if not wallet or Decimal(str(wallet.locked_uzs)) < amount:
                return "locked"

            balance_before = Decimal(str(wallet.uzs_balance))
            refunded_wallet = unlock_uzs_balance(db, withdraw.telegram_id, amount)
            if not refunded_wallet:
                return "locked"

            now = datetime.now(timezone.utc)
            withdraw.status = "REJECTED"
            withdraw.rejected_by = admin_id
            withdraw.rejected_at = now
            withdraw.reject_reason = reason
            withdraw.processing_seconds = _processing_seconds(withdraw.created_at, now)
            create_transaction(
                db=db,
                telegram_id=withdraw.telegram_id,
                currency="UZS",
                amount=amount,
                balance_before=balance_before,
                balance_after=Decimal(str(refunded_wallet.uzs_balance)),
                type="WITHDRAW_REJECTED",
                description="Pul yechish rad etildi. Mablag‘ balansga qaytarildi.",
                commit=False,
            )
            db.flush()
            return withdraw
    except SQLAlchemyError:
        return "operation_failed"
def get_withdraws(db: Session):
    return db.query(Withdraw).order_by(Withdraw.id.desc()).all()
def get_pending_withdraws(db: Session):
    return db.query(Withdraw).filter(Withdraw.status == "PENDING").order_by(Withdraw.id.desc()).all()
def get_completed_withdraws(db: Session):
    return db.query(Withdraw).filter(Withdraw.status.in_(["APPROVED", "REJECTED"])).order_by(Withdraw.id.desc()).all()
