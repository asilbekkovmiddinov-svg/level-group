from sqlalchemy.orm import Session
from decimal import Decimal

from app.models.transaction import Transaction


def create_transaction(
    db: Session,
    telegram_id: int,
    currency: str,
    amount: Decimal,
    balance_before: Decimal,
    balance_after: Decimal,
    type: str,
    description: str = None,
    commit: bool = True,
):
    transaction = Transaction(
        telegram_id=telegram_id,
        currency=currency,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        type=type,
        description=description
    )

    db.add(transaction)
    db.flush()

    if commit:
        db.commit()
        db.refresh(transaction)

    return transaction
