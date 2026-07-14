from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.crud.deposit import create_deposit
from app.crud.withdraw import create_withdraw
from app.models.deposit import Deposit
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.models.withdraw import Withdraw
from app.schemas.deposit import DepositCreate
from app.schemas.withdraw import WithdrawCreate


def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, Wallet.__table__, Deposit.__table__, Withdraw.__table__, Transaction.__table__],
    )
    db = sessionmaker(bind=engine)()
    db.add(User(telegram_id=42, first_name="Ali"))
    db.add(Wallet(telegram_id=42, uzs_balance=100000, locked_uzs=0, efc_balance=0, locked_efc=0))
    db.commit()
    return db


def test_deposit_create_replays_key_and_enforces_one_active_request():
    db = session()
    first = create_deposit(db, DepositCreate(amount=15000), 42, "deposit-key")
    replay = create_deposit(db, DepositCreate(amount=15000), 42, "deposit-key")
    other_device = create_deposit(db, DepositCreate(amount=20000), 42, "other-key")
    conflict = create_deposit(db, DepositCreate(amount=20000), 42, "deposit-key")
    assert first.id == replay.id == other_device.id
    assert conflict == "idempotency_conflict"
    assert db.query(Deposit).count() == 1


def test_withdraw_create_replays_without_double_lock_or_transaction():
    db = session()
    data = WithdrawCreate(amount=20000, card_number="8600", card_holder="Ali", bank_name="Bank")
    first = create_withdraw(db, data, 42, "withdraw-key")
    replay = create_withdraw(db, data, 42, "withdraw-key")
    other_device = create_withdraw(
        db,
        WithdrawCreate(amount=25000, card_number="9860", card_holder="Ali", bank_name="Bank"),
        42,
        "other-key",
    )
    assert first.id == replay.id == other_device.id
    assert db.query(Withdraw).count() == 1
    assert db.query(Transaction).filter(Transaction.type == "WITHDRAW_REQUEST").count() == 1
    wallet = db.query(Wallet).filter(Wallet.telegram_id == 42).one()
    assert float(wallet.uzs_balance) == 80000 and float(wallet.locked_uzs) == 20000
