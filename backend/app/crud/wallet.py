from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.wallet import Wallet


def to_decimal(amount):
    return Decimal(str(amount))


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
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

    wallet.uzs_balance += amount

    db.commit()
    db.refresh(wallet)

    return wallet


def subtract_uzs_balance(
    db: Session,
    telegram_id: int,
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

    if wallet.uzs_balance < amount:
        return None

    wallet.uzs_balance -= amount

    db.commit()
    db.refresh(wallet)

    return wallet


def lock_uzs_balance(
    db: Session,
    telegram_id: int,
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

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
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

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
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

    if wallet.locked_uzs < amount:
        return None

    wallet.locked_uzs -= amount

    db.commit()
    db.refresh(wallet)

    return wallet


def add_efc_balance(
    db: Session,
    telegram_id: int,
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

    wallet.efc_balance += amount

    db.commit()
    db.refresh(wallet)

    return wallet


def subtract_efc_balance(
    db: Session,
    telegram_id: int,
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

    if wallet.efc_balance < amount:
        return None

    wallet.efc_balance -= amount

    db.commit()
    db.refresh(wallet)

    return wallet


def lock_efc_balance(
    db: Session,
    telegram_id: int,
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

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
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

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
    amount,
):
    wallet = get_or_create_wallet(db, telegram_id)
    amount = to_decimal(amount)

    if wallet.locked_efc < amount:
        return None

    wallet.locked_efc -= amount

    db.commit()
    db.refresh(wallet)

    return wallet


# Eski fayllardagi importlar uchun aliaslar

def add_efc(db: Session, telegram_id: int, amount):
    return add_efc_balance(db, telegram_id, amount)


def subtract_efc(db: Session, telegram_id: int, amount):
    return subtract_efc_balance(db, telegram_id, amount)


def add_uzs(db: Session, telegram_id: int, amount):
    return add_uzs_balance(db, telegram_id, amount)


def subtract_uzs(db: Session, telegram_id: int, amount):
    return subtract_uzs_balance(db, telegram_id, amount)


def lock_uzs(db: Session, telegram_id: int, amount):
    return lock_uzs_balance(db, telegram_id, amount)


def unlock_uzs_after_withdraw(
    db: Session,
    telegram_id: int,
    amount,
):
    return unlock_uzs_balance(db, telegram_id, amount)


def confirm_uzs_withdraw(
    db: Session,
    telegram_id: int,
    amount,
):
    return confirm_locked_uzs(db, telegram_id, amount)
