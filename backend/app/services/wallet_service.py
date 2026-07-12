from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.crud.transaction import create_transaction
from app.crud.wallet import add_efc_balance, to_decimal


class WalletOperationError(Exception):
    pass


class InvalidWalletAmountError(WalletOperationError):
    pass


class WalletOperationFailedError(WalletOperationError):
    pass


def add_efc_with_transaction(
    db: Session,
    telegram_id: int,
    amount,
    transaction_type: str,
    description: str,
):
    value = to_decimal(amount)
    if value is None:
        raise InvalidWalletAmountError("Amount must be greater than zero")

    try:
        with db.begin():
            wallet = add_efc_balance(db, telegram_id, value)
            if wallet is None:
                raise WalletOperationFailedError("Wallet balance operation failed")

            balance_after = Decimal(str(wallet.efc_balance))
            create_transaction(
                db=db,
                telegram_id=telegram_id,
                currency="EFC",
                amount=value,
                balance_before=balance_after - value,
                balance_after=balance_after,
                type=transaction_type,
                description=description,
                commit=False,
            )
            db.refresh(wallet)
            return wallet
    except WalletOperationError:
        raise
    except SQLAlchemyError as error:
        raise WalletOperationFailedError("Wallet operation could not be completed") from error
