from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.wallet import Wallet


def get_wallet(db: Session, telegram_id: int):
    return db.query(Wallet).filter(
        Wallet.telegram_id == telegram_id
    ).first()


def create_wallet(db: Session, telegram_id: int):
    wallet = Wallet(
        telegram_id=telegram_id,
        efc_balance=0,
        uzs_balance=0,
        locked_efc=0,
        locked_uzs=0
    )

    db.add(wallet)
    db.commit()
    db.refresh(wallet)

    return wallet
    
def add_efc(db: Session, telegram_id: int, amount: float):
    wallet = get_wallet(db, telegram_id)

    if not wallet:
        return None

    amount_decimal = Decimal(str(amount))

    before = wallet.efc_balance
    wallet.efc_balance = wallet.efc_balance + amount_decimal

    db.commit()
    db.refresh(wallet)

    return before, wallet.efc_balan
    
def add_uzs(db: Session, telegram_id: int, amount: float):
    wallet = get_wallet(db, telegram_id)

    if not wallet:
        return None

    amount_decimal = Decimal(str(amount))

    before = wallet.uzs_balance
    wallet.uzs_balance = wallet.uzs_balance + amount_decimal

    db.commit()
    db.refresh(wallet)

    return before, wallet.uzs_balance
