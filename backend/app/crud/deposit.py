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


def approve_deposit(
    db: Session,
    deposit_id: int,
    admin_id: int
):
    deposit = db.query(Deposit).filter(
        Deposit.id == deposit_id
    ).first()

    if not deposit:
        return None

    if deposit.status == "APPROVED":
        return "approved"

    result = add_uzs(
        db,
        deposit.telegram_id,
        float(deposit.amount)
    )

    if not result:
        return None

    before, after = result

    create_transaction(
        db=db,
        telegram_id=deposit.telegram_id,
        currency="UZS",
        amount=float(deposit.amount),
        balance_before=before,
        balance_after=after,
        type="DEPOSIT",
        description="Deposit approved by admin"
    )

    deposit.status = "APPROVED"
    deposit.approved_by = admin_id
    deposit.approved_at = datetime.utcnow()

    db.commit()
    db.refresh(deposit)

    return deposit
