from sqlalchemy.orm import Session

from app.models.transaction import Transaction


def create_transaction(
    db: Session,
    telegram_id: int,
    currency: str,
    amount: float,
    balance_before: float,
    balance_after: float,
    transaction_type: str,
    description: str = None
):
    transaction = Transaction(
        telegram_id=telegram_id,
        currency=currency,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        type=transaction_type,
        description=description
    )

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return transaction
