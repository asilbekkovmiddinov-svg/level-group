from datetime import datetime

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
    deposit.claimed_at = datetime.utcnow()

    db.commit()
    db.refresh(deposit)

    return deposit


def approve_deposit(db: Session, deposit_id: int, admin_id: int):
    deposit = db.query(Deposit).filter(
        Deposit.id == deposit_id
    ).first()

    if not deposit:
        return None

    if deposit.status != "CLAIMED":
        return "invalid_status"

    result = add_uzs(
        db=db,
        telegram_id=deposit.telegram_id,
        amount=float(deposit.amount)
    )

    if not result:
        return "wallet_not_found"

    before, after = result

    create_transaction(
        db=db,
        telegram_id=deposit.telegram_id,
        currency="UZS",
        amount=float(deposit.amount),
        balance_before=before,
        balance_after=after,
        type="DEPOSIT",
        description=f"Deposit #{deposit.id} approved"
    )

    now = datetime.utcnow()

    deposit.status = "COMPLETED"
    deposit.completed_by = admin_id
    deposit.completed_at = now

    if deposit.claimed_at:
        deposit.processing_seconds = int(
            (now - deposit.claimed_at).total_seconds()
        )

    db.commit()
    db.refresh(deposit)

    return deposit


def reject_deposit(db: Session, deposit_id: int, admin_id: int, reason: str):
    deposit = db.query(Deposit).filter(
        Deposit.id == deposit_id
    ).first()

    if not deposit:
        return None

    if deposit.status != "CLAIMED":
        return "invalid_status"

    now = datetime.utcnow()

    deposit.status = "REJECTED"
    deposit.rejected_by = admin_id
    deposit.rejected_at = now
    deposit.reject_reason = reason

    if deposit.claimed_at:
        deposit.processing_seconds = int(
            (now - deposit.claimed_at).total_seconds()
        )

    db.commit()
    db.refresh(deposit)

    return deposit
