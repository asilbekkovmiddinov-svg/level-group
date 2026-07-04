from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.deposit import Deposit
from app.schemas.deposit import DepositCreate
from app.crud.wallet import add_uzs
from app.crud.transaction import create_transaction


def create_deposit(db: Session, data: DepositCreate):
    deposit = Deposit(
        telegram_id=data.telegram_id,
        amount=data.amount,
        status="PENDING"
    )

    db.add(deposit)
    db.commit()
    db.refresh(deposit)

    return deposit


def get_deposits(db: Session):
    return db.query(Deposit).order_by(
        Deposit.id.desc()
    ).all()


def get_pending_deposits(db: Session):
    return db.query(Deposit).filter(
        Deposit.status == "PENDING"
    ).order_by(Deposit.id.asc()).all()


def get_claimed_deposits(db: Session):
    return db.query(Deposit).filter(
        Deposit.status == "CLAIMED"
    ).order_by(Deposit.claimed_at.asc()).all()


def claim_deposit(db: Session, deposit_id: int, admin_id: int):
    deposit = db.query(Deposit).filter(
        Deposit.id == deposit_id
    ).first()

    if not deposit:
        return None

    if deposit.status != "PENDING":
        return "already_claimed"

    deposit.status = "CLAIMED"
    deposit.claimed_by = admin_id
    deposit.claimed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(deposit)

    return deposit
