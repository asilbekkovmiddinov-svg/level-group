from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.transaction import Transaction


router = APIRouter(prefix="/transactions", tags=["Transactions"])

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
CURRENCIES = {"EFC", "UZS"}
DIRECTIONS = {"CREDIT", "DEBIT"}
CREDIT_TRANSACTION_TYPES = {
    "ADMIN_ADD_EFC",
    "DEPOSIT",
    "MATCH_REWARD",
    "MATCH_UNLOCK",
    "ORDER_REFUND",
    "ORDER_REJECT_REFUND",
    "P2P_OWNER_COMPLETE",
    "P2P_REJECT",
    "WHEEL_REWARD",
    "WITHDRAW_REJECTED",
}


def transaction_direction(transaction_type: str) -> str:
    return "CREDIT" if transaction_type in CREDIT_TRANSACTION_TYPES else "DEBIT"


def transaction_item(transaction: Transaction) -> dict:
    return {
        "id": transaction.id,
        "currency": transaction.currency,
        "amount": float(transaction.amount),
        "direction": transaction_direction(transaction.type),
        "transaction_type": transaction.type,
        "status": transaction.status,
        "description": transaction.description,
        "reference_type": None,
        "reference_id": None,
        "created_at": transaction.created_at,
    }


@router.get("")
def get_transactions(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    currency: str | None = None,
    direction: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    transaction_type: str | None = None,
):
    currency = currency.upper() if currency else None
    direction = direction.upper() if direction else None
    if currency and currency not in CURRENCIES:
        raise HTTPException(status_code=400, detail="currency must be EFC or UZS")
    if direction and direction not in DIRECTIONS:
        raise HTTPException(status_code=400, detail="direction must be CREDIT or DEBIT")
    if status_filter is not None and not status_filter.strip():
        raise HTTPException(status_code=400, detail="status must not be empty")
    if transaction_type is not None and not transaction_type.strip():
        raise HTTPException(status_code=400, detail="transaction_type must not be empty")

    try:
        query = db.query(Transaction).filter(
            Transaction.telegram_id == current_user.telegram_id
        )
        if currency:
            query = query.filter(Transaction.currency == currency)
        if direction == "CREDIT":
            query = query.filter(Transaction.type.in_(CREDIT_TRANSACTION_TYPES))
        elif direction == "DEBIT":
            query = query.filter(~Transaction.type.in_(CREDIT_TRANSACTION_TYPES))
        if status_filter:
            query = query.filter(Transaction.status == status_filter.upper())
        if transaction_type:
            query = query.filter(Transaction.type == transaction_type.upper())

        total = query.count()
        transactions = query.order_by(
            Transaction.created_at.desc(), Transaction.id.desc()
        ).offset(offset).limit(limit).all()
    except SQLAlchemyError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Transaction history is temporarily unavailable",
        )

    return {
        "items": [transaction_item(transaction) for transaction in transactions],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(transactions) < total,
    }
