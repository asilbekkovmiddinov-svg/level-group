from datetime import datetime

from sqlalchemy.orm import Session

from app.models.withdraw import Withdraw
from app.schemas.withdraw import WithdrawCreate


def create_withdraw(
    db: Session,
    data: WithdrawCreate
):
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


def approve_withdraw(
    db: Session,
    withdraw_id: int,
    admin_id: int
):
    withdraw = db.query(Withdraw).filter(
        Withdraw.id == withdraw_id
    ).first()

    if not withdraw:
        return None

    if withdraw.status == "APPROVED":
        return "approved"

    withdraw.status = "APPROVED"
    withdraw.approved_by = admin_id
    withdraw.approved_at = datetime.utcnow()

    db.commit()
    db.refresh(withdraw)

    return withdraw
