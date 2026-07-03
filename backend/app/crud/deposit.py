from sqlalchemy.orm import Session

from app.models.deposit import Deposit
from app.schemas.deposit import DepositCreate


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
    return db.query(Deposit).order_by(Deposit.id.desc()).all()
