from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.withdraw import Withdraw
from app.schemas.withdraw import WithdrawCreate
from app.crud.wallet import (
    get_wallet,
    lock_uzs,
    subtract_uzs,
    unlock_uzs_after_withdraw,
    confirm_uzs_withdraw,
)
from app.crud.transaction import create_transaction


def to_decimal(amount):
    return Decimal(str(amount))


def calculate_processing_seconds(created_at):
    if not created_at:
        return None

    now = datetime.utcnow()

    if created_at.tzinfo is not None:
        created_at = created_at.replace(tzinfo=None)

    return int((now - created_at).total_seconds())


def create_withdraw(db: Session, data: WithdrawCreate):
    amount = to_decimal(data.amount)

    result = lock_uzs(
        db=db,
        telegram_id=data.telegram_id,
        amount=amount,
    )

    if not result:
        return "insufficient"

    withdraw = Withdraw(
        telegram_id=data.telegram_id,
        amount=amount,
        card_number=data.card_number,
        card_holder=data.card_holder,
        bank_name=data.bank_name,
        status="PENDING",
    )

    db.add(withdraw)
    db.commit()
    db.refresh(withdraw)

    create_transaction(
        db=db,
        telegram_id=data.telegram_id,
        currency="UZS",
        amount=amount,
        balance_before=result.uzs_balance + amount,
        balance_after=result.uzs_balance,
        type="WITHDRAW_REQUEST",
        description="Pul yechish so‘rovi yaratildi. Muddat: 24 soatgacha.",
    )

    return withdraw


def claim_withdraw(db: Session, withdraw_id: int, admin_id: int):
    withdraw = db.query(Withdraw).filter(
        Withdraw.id == withdraw_id
    ).first()

    if not withdraw:
        return None

    if withdraw.status != "PENDING":
        return "not_pending"

    if withdraw.claimed_by and withdraw.claimed_by != admin_id:
        return "already_claimed"

    withdraw.claimed_by = admin_id
    withdraw.claimed_at = datetime.utcnow()

    db.commit()
    db.refresh(withdraw)

    return withdraw


def get_withdraws(db: Session):
    return db.query(Withdraw).order_by(
        Withdraw.id.desc()
    ).all()


def get_pending_withdraws(db: Session):
    return db.query(Withdraw).filter(
        Withdraw.status == "PENDING"
    ).order_by(
        Withdraw.id.desc()
    ).all()
def get_completed_withdraws(db: Session):
    return db.query(Withdraw).filter(
        Withdraw.status.in_(["APPROVED", "REJECTED"])
    ).order_by(
        Withdraw.id.desc()
    ).all()


def approve_withdraw(db: Session, withdraw_id: int, admin_id: int):
    withdraw = db.query(Withdraw).filter(
        Withdraw.id == withdraw_id
    ).first()

    if not withdraw:
        return None

    if withdraw.status == "APPROVED":
        return "approved"

    if withdraw.status == "REJECTED":
        return "rejected"

    if withdraw.claimed_by and withdraw.claimed_by != admin_id:
        return "not_owner"

    amount = to_decimal(withdraw.amount)

    result = confirm_uzs_withdraw(
        db=db,
        telegram_id=withdraw.telegram_id,
        amount=amount,
    )

    if not result:
        wallet = get_wallet(db, withdraw.telegram_id)

        if not wallet or wallet.uzs_balance < amount:
            return "locked"

        result = subtract_uzs(
            db=db,
            telegram_id=withdraw.telegram_id,
            amount=amount,
        )

        if not result:
            return "locked"

    withdraw.status = "APPROVED"
    withdraw.approved_by = admin_id
    withdraw.approved_at = datetime.utcnow()
    withdraw.processing_seconds = calculate_processing_seconds(
        withdraw.created_at
    )

    db.commit()
    db.refresh(withdraw)

    create_transaction(
        db=db,
        telegram_id=withdraw.telegram_id,
        currency="UZS",
        amount=amount,
        balance_before=result.uzs_balance + amount,
        balance_after=result.uzs_balance,
        type="WITHDRAW_APPROVED",
        description="Pul yechish admin tomonidan tasdiqlandi.",
    )

    return withdraw


def reject_withdraw(
    db: Session,
    withdraw_id: int,
    admin_id: int,
    reason: str = "Admin rad etdi",
):
    withdraw = db.query(Withdraw).filter(
        Withdraw.id == withdraw_id
    ).first()

    if not withdraw:
        return None

    if withdraw.status == "APPROVED":
        return "approved"

    if withdraw.status == "REJECTED":
        return "rejected"

    if withdraw.claimed_by and withdraw.claimed_by != admin_id:
        return "not_owner"

    amount = to_decimal(withdraw.amount)

    result = unlock_uzs_after_withdraw(
        db=db,
        telegram_id=withdraw.telegram_id,
        amount=amount,
    )

    wallet = result or get_wallet(db, withdraw.telegram_id)

    withdraw.status = "REJECTED"
    withdraw.rejected_by = admin_id
    withdraw.rejected_at = datetime.utcnow()
    withdraw.reject_reason = reason
    withdraw.processing_seconds = calculate_processing_seconds(
        withdraw.created_at
    )

    db.commit()
    db.refresh(withdraw)

    if wallet:
        create_transaction(
            db=db,
            telegram_id=withdraw.telegram_id,
            currency="UZS",
            amount=amount,
            balance_before=wallet.uzs_balance - amount if result else wallet.uzs_balance,
            balance_after=wallet.uzs_balance,
            type="WITHDRAW_REJECTED",
            description="Pul yechish rad etildi. Mablag‘ balansga qaytarildi.",
        )

    return withdraw
