from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.crud.transaction import create_transaction
from app.crud.wallet import add_uzs_balance, get_wallet_for_update, to_decimal
from app.models.deposit import Deposit
from app.models.user import User
from app.schemas.deposit import DepositCreate

MIN_DEPOSIT_AMOUNT = Decimal("15000")


def _deposit_for_update(db: Session, deposit_id: int):
    return db.query(Deposit).filter(Deposit.id == deposit_id).with_for_update().first()


def _processing_seconds(claimed_at, now: datetime) -> int:
    if not claimed_at:
        return 0
    if claimed_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return max(0, int((now - claimed_at).total_seconds()))


def create_deposit(db: Session, data: DepositCreate, telegram_id: int, idempotency_key: str | None = None):
    amount = to_decimal(data.amount)
    if amount is None:
        return "invalid_amount"
    if amount < MIN_DEPOSIT_AMOUNT:
        return "minimum_amount"

    fingerprint = sha256(f"{amount:.2f}".encode()).hexdigest()
    try:
        with db.begin():
            db.query(User).filter(User.telegram_id == telegram_id).with_for_update().first()
            if idempotency_key:
                replay = db.query(Deposit).filter(
                    Deposit.telegram_id == telegram_id,
                    Deposit.idempotency_key == idempotency_key,
                ).first()
                if replay:
                    return replay if replay.request_fingerprint == fingerprint else "idempotency_conflict"
            active = db.query(Deposit).filter(
                Deposit.telegram_id == telegram_id,
                Deposit.status.in_(("PENDING", "CLAIMED")),
            ).order_by(Deposit.id.desc()).first()
            if active:
                return active
            deposit = Deposit(
                telegram_id=telegram_id, amount=amount, status="PENDING",
                idempotency_key=idempotency_key, request_fingerprint=fingerprint,
            )
            db.add(deposit)
            db.flush()
            return deposit
    except SQLAlchemyError:
        return "operation_failed"


def get_deposits(db: Session):
    return db.query(Deposit).order_by(Deposit.id.desc()).all()


def get_pending_deposits(db: Session):
    return db.query(Deposit).filter(Deposit.status == "PENDING").order_by(Deposit.id.asc()).all()


def get_claimed_deposits(db: Session):
    return db.query(Deposit).filter(Deposit.status == "CLAIMED").order_by(Deposit.claimed_at.asc()).all()


def claim_deposit(db: Session, deposit_id: int, admin_id: int, receipt_revision: int | None = None):
    try:
        with db.begin():
            deposit = _deposit_for_update(db, deposit_id)
            if not deposit:
                return None
            if deposit.status != "PENDING":
                return "already_claimed"
            if receipt_revision is not None and deposit.receipt_revision != receipt_revision:
                return "receipt_replaced"

            deposit.status = "CLAIMED"
            deposit.claimed_by = admin_id
            deposit.claimed_at = datetime.now(timezone.utc)
            deposit.claimed_receipt_revision = deposit.receipt_revision
            db.flush()
            return deposit
    except SQLAlchemyError:
        return "operation_failed"


def approve_deposit(db: Session, deposit_id: int, admin_id: int):
    try:
        with db.begin():
            deposit = _deposit_for_update(db, deposit_id)
            if not deposit:
                return None
            if deposit.status != "CLAIMED":
                return "invalid_status"
            if deposit.claimed_by != admin_id:
                return "not_owner"
            if deposit.claimed_receipt_revision != deposit.receipt_revision:
                return "receipt_replaced"

            wallet = get_wallet_for_update(db, deposit.telegram_id)
            if not wallet:
                return "wallet_not_found"

            amount = Decimal(str(deposit.amount))
            balance_before = Decimal(str(wallet.uzs_balance))
            updated_wallet = add_uzs_balance(db, deposit.telegram_id, amount)
            if not updated_wallet:
                return "wallet_not_found"

            balance_after = Decimal(str(updated_wallet.uzs_balance))
            create_transaction(
                db=db,
                telegram_id=deposit.telegram_id,
                currency="UZS",
                amount=amount,
                balance_before=balance_before,
                balance_after=balance_after,
                type="DEPOSIT",
                description=f"Deposit #{deposit.id} approved",
                commit=False,
            )

            now = datetime.now(timezone.utc)
            deposit.status = "APPROVED"
            deposit.approved_by = admin_id
            deposit.approved_at = now
            deposit.completed_by = admin_id
            deposit.completed_at = now
            deposit.processing_seconds = _processing_seconds(deposit.claimed_at, now)
            db.flush()
            return deposit
    except SQLAlchemyError:
        return "operation_failed"


def reject_deposit(db: Session, deposit_id: int, admin_id: int, reason: str):
    try:
        with db.begin():
            deposit = _deposit_for_update(db, deposit_id)
            if not deposit:
                return None
            if deposit.status != "CLAIMED":
                return "invalid_status"
            if deposit.claimed_by != admin_id:
                return "not_owner"
            if deposit.claimed_receipt_revision != deposit.receipt_revision:
                return "receipt_replaced"

            now = datetime.now(timezone.utc)
            deposit.status = "REJECTED"
            deposit.rejected_by = admin_id
            deposit.rejected_at = now
            deposit.reject_reason = reason
            deposit.processing_seconds = _processing_seconds(deposit.claimed_at, now)
            db.flush()
            return deposit
    except SQLAlchemyError:
        return "operation_failed"
