from datetime import datetime

from sqlalchemy.orm import Session

from app.models.withdraw import Withdraw
from app.schemas.withdraw import WithdrawCreate
from app.crud.wallet import lock_uzs, unlock_uzs_after_withdraw
from app.crud.transaction import create_transaction


def create_withdraw(db: Session, data: WithdrawCreate):
    result = lock_uzs(db, data.telegram_id, data.amount)

    if result == "insufficient":
        return "insufficient"

    if not result:
        return None

    withdraw = Withdraw(
        telegram_id=data.telegram_id,
        amount=data.amount,
        status="PENDING"
    )

    db.add(withdraw)
    db.commit()
    db.refresh(withdraw)

    return withdraw


def get_withdraws(db: Session):
    return db.query(Withdraw).order_by(
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

    result = unlock_uzs_after_withdraw(
        db,
        withdraw.telegram_id,
        float(withdraw.amount)
    )

    if result == "insufficient_locked":
        return "locked"

    if not result:
        return None

    before, after = result

    create_transaction(
        db=db,
        telegram_id=withdraw.telegram_id,
        currency="UZS",
        amount=float(withdraw.amount),
        balance_before=before,
        balance_after=after,
        type="WITHDRAW",
        description="Withdraw approved by admin"
    )

    withdraw.status = "APPROVED"
    withdraw.approved_by = admin_id
    withdraw.approved_at = datetime.utcnow()

    db.commit()
    db.refresh(withdraw)

    return withdraw
