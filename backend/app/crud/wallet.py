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
        efc_balance=Decimal("0"),
        uzs_balance=Decimal("0"),
        locked_efc=Decimal("0"),
        locked_uzs=Decimal("0"),
    )

    db.add(wallet)
    db.commit()
    db.refresh(wallet)

    return wallet


def get_or_create_wallet(db: Session, telegram_id: int):
    wallet = get_wallet(db, telegram_id)

    if wallet:
        return wallet

    return create_wallet(db, telegram_id)


def add_uzs_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)

    wallet.uzs_balance += Decimal(amount)

    db.commit()
    db.refresh(wallet)

    return wallet


def subtract_uzs_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.uzs_balance < amount:
        return None

    wallet.uzs_balance -= amount

    db.commit()
    db.refresh(wallet)

    return wallet


def lock_uzs_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.uzs_balance < amount:
        return None

    wallet.uzs_balance -= amount
    wallet.locked_uzs += amount

    db.commit()
    db.refresh(wallet)

    return wallet
def unlock_uzs_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.locked_uzs < amount:
        return None

    wallet.locked_uzs -= amount
    wallet.uzs_balance += amount

    db.commit()
    db.refresh(wallet)

    return wallet


def confirm_locked_uzs(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.locked_uzs < amount:
        return None

    wallet.locked_uzs -= amount

    db.commit()
    db.refresh(wallet)

    return wallet


def add_efc_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)

    wallet.efc_balance += Decimal(amount)

    db.commit()
    db.refresh(wallet)

    return wallet


def subtract_efc_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.efc_balance < amount:
        return None

    wallet.efc_balance -= amount

    db.commit()
    db.refresh(wallet)

    return wallet


def lock_efc_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.efc_balance < amount:
        return None

    wallet.efc_balance -= amount
    wallet.locked_efc += amount

    db.commit()
    db.refresh(wallet)

    return wallet


def unlock_efc_balance(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.locked_efc < amount:
        return None

    wallet.locked_efc -= amount
    wallet.efc_balance += amount

    db.commit()
    db.refresh(wallet)

    return wallet


def confirm_locked_efc(
    db: Session,
    telegram_id: int,
    amount: Decimal,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = Decimal(amount)

    if wallet.locked_efc < amount:
        return None

    wallet.locked_efc -= amount

    db.commit()
    db.refresh(wallet)

    return wallet
# Compatibility aliases
# Eski importlar xato bermasligi uchun

def add_efc(db: Session, telegram_id: int, amount: Decimal):
    return add_efc_balance(db, telegram_id, amount)


def subtract_efc(db: Session, telegram_id: int, amount: Decimal):
    return subtract_efc_balance(db, telegram_id, amount)


def add_uzs(db: Session, telegram_id: int, amount: Decimal):
    return add_uzs_balance(db, telegram_id, amount)


def subtract_uzs(db: Session, telegram_id: int, amount: Decimal):
    return subtract_uzs_balance(db, telegram_id, amount)
