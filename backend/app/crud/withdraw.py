from datetime import datetime

from sqlalchemy.orm import Session

from app.models.withdraw import Withdraw
from app.schemas.withdraw import WithdrawCreate
from app.crud.wallet import (
    lock_uzs,
    unlock_uzs_after_withdraw,
    confirm_uzs_withdraw,
)
from app.crud.transaction import create_transaction


def create_withdraw(db: Session, data: WithdrawCreate):
    result = lock_uzs(
        db=db,
        telegram_id=data.telegram_id,
        amount=data.amount,
    )

    if not result:
        return "insufficient"

    withdraw = Withdraw(
        telegram_id=data.telegram_id,
        amount=data.amount,
        status="PENDING",
    )

    db.add(withdraw)
    db.commit()
    db.refresh(withdraw)

    create_transaction(
        db=db,
        telegram_id=data.telegram_id,
        currency="UZS",
        amount=data.amount,
        balance_before=result.uzs_balance + data.amount,
        balance_after=result.uzs_balance,
        type="WITHDRAW_REQUEST",
        status="PENDING",
        description="Pul yechish so‘rovi yaratildi. Muddat: 24 soatgacha.",
    )

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
def approve_withdraw(
    db: Session,
    withdraw_id: int,
    admin_id: int,
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

    result = confirm_uzs_withdraw(
        db=db,
        telegram_id=withdraw.telegram_id,
        amount=withdraw.amount,
    )

    if not result:
        return "locked"

    withdraw.status = "APPROVED"
    withdraw.approved_by = admin_id
    withdraw.approved_at = datetime.utcnow()

    db.commit()
    db.refresh(withdraw)

    create_transaction(
        db=db,
        telegram_id=withdraw.telegram_id,
        currency="UZS",
        amount=withdraw.amount,
        balance_before=result.uzs_balance,
        balance_after=result.uzs_balance,
        type="WITHDRAW_APPROVED",
        status="SUCCESS",
        description="Pul yechish admin tomonidan tasdiqlandi.",
    )

    return withdraw


def reject_withdraw(
    db: Session,
    withdraw_id: int,
    admin_id: int,
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

    result = unlock_uzs_after_withdraw(
        db=db,
        telegram_id=withdraw.telegram_id,
        amount=withdraw.amount,
    )

    if not result:
        return "locked"

    withdraw.status = "REJECTED"
    withdraw.approved_by = admin_id
    withdraw.approved_at = datetime.utcnow()

    db.commit()
    db.refresh(withdraw)

    create_transaction(
        db=db,
        telegram_id=withdraw.telegram_id,
        currency="UZS",
        amount=withdraw.amount,
        balance_before=result.uzs_balance - withdraw.amount,
        balance_after=result.uzs_balance,
        type="WITHDRAW_REJECTED",
        status="CANCELLED",
        description="Pul yechish rad etildi. Mablag‘ balansga qaytarildi.",
    )

    return withdraw
