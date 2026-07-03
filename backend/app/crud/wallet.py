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

    before = wallet.efc_balance

    wallet.efc_balance += amount

    db.commit()
    db.refresh(wallet)

    return before, wallet.efc_balance
