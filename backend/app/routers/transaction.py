from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.transaction import Transaction

router = APIRouter(
    prefix="/transactions",
    tags=["Transactions"]
)


@router.get("/{telegram_id}")
def get_transactions(
    telegram_id: int,
    db: Session = Depends(get_db)
):
    transactions = db.query(Transaction).filter(
        Transaction.telegram_id == telegram_id
    ).order_by(Transaction.id.desc()).all()

    return transactions
