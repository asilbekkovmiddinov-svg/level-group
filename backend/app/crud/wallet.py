from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models.wallet import Wallet


ZERO = Decimal("0")


def to_decimal(amount) -> Decimal | None:
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        return None

    if not value.is_finite() or value <= ZERO:
        return None

    return value


def get_wallet(db: Session, telegram_id: int):
    return db.query(Wallet).filter(Wallet.telegram_id == telegram_id).first()


def get_wallet_for_update(db: Session, telegram_id: int):
    return (
        db.query(Wallet)
        .filter(Wallet.telegram_id == telegram_id)
        .with_for_update()
        .first()
    )


def create_wallet(db: Session, telegram_id: int):
    wallet = Wallet(
        telegram_id=telegram_id,
        efc_balance=ZERO,
        uzs_balance=ZERO,
        locked_efc=ZERO,
        locked_uzs=ZERO,
    )
    db.add(wallet)
    db.commit()
    db.refresh(wallet)
    return wallet


def get_or_create_wallet(db: Session, telegram_id: int):
    wallet = get_wallet_for_update(db, telegram_id)
    if wallet:
        return wallet

    wallet = Wallet(
        telegram_id=telegram_id,
        efc_balance=ZERO,
        uzs_balance=ZERO,
        locked_efc=ZERO,
        locked_uzs=ZERO,
    )
    db.add(wallet)
    db.flush()
    return wallet


def _change_balance(db: Session, telegram_id: int, currency: str, action: str, amount):
    value = to_decimal(amount)
    if value is None:
        return None

    wallet = get_or_create_wallet(db, telegram_id)
    balance_field = "efc_balance" if currency == "EFC" else "uzs_balance"
    locked_field = "locked_efc" if currency == "EFC" else "locked_uzs"
    balance = Decimal(str(getattr(wallet, balance_field)))
    locked = Decimal(str(getattr(wallet, locked_field)))

    if action == "add":
        setattr(wallet, balance_field, balance + value)
    elif action == "subtract":
        if balance < value:
            return None
        setattr(wallet, balance_field, balance - value)
    elif action == "lock":
        if balance < value:
            return None
        setattr(wallet, balance_field, balance - value)
        setattr(wallet, locked_field, locked + value)
    elif action == "unlock":
        if locked < value:
            return None
        setattr(wallet, locked_field, locked - value)
        setattr(wallet, balance_field, balance + value)
    elif action == "confirm":
        if locked < value:
            return None
        setattr(wallet, locked_field, locked - value)
    else:
        raise ValueError("Unknown wallet action")

    db.flush()
    return wallet


def add_uzs_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "UZS", "add", amount)


def subtract_uzs_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "UZS", "subtract", amount)


def lock_uzs_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "UZS", "lock", amount)


def unlock_uzs_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "UZS", "unlock", amount)


def confirm_locked_uzs(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "UZS", "confirm", amount)


def add_efc_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "EFC", "add", amount)


def subtract_efc_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "EFC", "subtract", amount)


def lock_efc_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "EFC", "lock", amount)


def unlock_efc_balance(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "EFC", "unlock", amount)


def confirm_locked_efc(db: Session, telegram_id: int, amount):
    return _change_balance(db, telegram_id, "EFC", "confirm", amount)


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


def unlock_uzs_after_withdraw(db: Session, telegram_id: int, amount):
    return unlock_uzs_balance(db, telegram_id, amount)


def confirm_uzs_withdraw(db: Session, telegram_id: int, amount):
    return confirm_locked_uzs(db, telegram_id, amount)
