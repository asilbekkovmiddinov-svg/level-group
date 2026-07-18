from decimal import Decimal
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.database import get_db
from app.core import telegram_auth
from app.crud.order import approve_order
from app.models.order import Order
from app.models.referral import Referral, ReferralProfile, ReferralReward
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.schemas.user import InternalUserRegister
from app.services.internal_users import register_internal_user
from app.services.referrals import ensure_referral_profile, referral_summary
from app.routers.referral import router as referral_router


def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Wallet.__table__,
            Transaction.__table__,
            Order.__table__,
            ReferralProfile.__table__,
            Referral.__table__,
            ReferralReward.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def add_user(db, telegram_id: int, balance: str = "0"):
    db.add(User(telegram_id=telegram_id, first_name=f"User {telegram_id}"))
    db.add(
        Wallet(
            telegram_id=telegram_id,
            uzs_balance=Decimal(balance),
            efc_balance=0,
            locked_uzs=0,
            locked_efc=0,
        )
    )
    db.flush()


def init_data(telegram_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": telegram_id, "first_name": "Referral User"},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", b"test-token", hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_new_referral_is_linked_once_and_credits_registration_bonus():
    sessions = session_factory()
    db = sessions()
    add_user(db, 100)
    code = ensure_referral_profile(db, 100).referral_code
    db.commit()

    result = register_internal_user(
        db,
        InternalUserRegister(
            telegram_id=200,
            first_name="Referred",
            referral_code=code,
        ),
    )
    assert result.created is True
    assert db.query(Referral).filter(Referral.referred_telegram_id == 200).count() == 1
    assert Decimal(str(db.get(Wallet, 100).uzs_balance)) == Decimal("1000")
    reward = db.query(ReferralReward).one()
    assert reward.reward_type == "REGISTRATION"
    assert Decimal(str(reward.amount)) == Decimal("1000")
    assert db.query(Transaction).filter(
        Transaction.type == "REFERRAL_REGISTRATION_BONUS"
    ).count() == 1

    replay = register_internal_user(
        db,
        InternalUserRegister(
            telegram_id=200,
            first_name="Referred",
            referral_code=code,
        ),
    )
    assert replay.created is False
    assert db.query(Referral).count() == 1
    assert db.query(ReferralReward).count() == 1
    assert Decimal(str(db.get(Wallet, 100).uzs_balance)) == Decimal("1000")


def test_first_completed_shop_order_credits_bonus_only_once():
    sessions = session_factory()
    db = sessions()
    add_user(db, 101)
    code = ensure_referral_profile(db, 101).referral_code
    db.commit()
    register_internal_user(
        db,
        InternalUserRegister(
            telegram_id=201,
            first_name="Buyer",
            referral_code=code,
        ),
    )

    for order_id in (1, 2):
        db.add(
            Order(
                id=order_id,
                order_number=f"{order_id:08d}",
                telegram_id=201,
                product_id=7,
                product_title="130 Coins",
                coins_amount=130,
                price_uzs=25000,
                status="CLAIMED",
                claimed_by=700,
            )
        )
    db.commit()

    assert approve_order(db, 1, 700).status == "COMPLETED"
    assert Decimal(str(db.get(Wallet, 101).uzs_balance)) == Decimal("6000")
    assert approve_order(db, 2, 700).status == "COMPLETED"
    assert Decimal(str(db.get(Wallet, 101).uzs_balance)) == Decimal("6000")
    assert db.query(ReferralReward).filter(
        ReferralReward.reward_type == "FIRST_SHOP_COMPLETION"
    ).count() == 1
    summary = referral_summary(db, 101)
    assert summary["total_referrals"] == 1
    assert summary["coin_shop_buyers"] == 1
    assert summary["total_earned_uzs"] == Decimal("6000.00")


def test_rejected_or_uncompleted_shop_order_does_not_credit_purchase_bonus():
    sessions = session_factory()
    db = sessions()
    add_user(db, 102)
    code = ensure_referral_profile(db, 102).referral_code
    db.commit()
    register_internal_user(
        db,
        InternalUserRegister(
            telegram_id=202,
            first_name="Buyer",
            referral_code=code,
        ),
    )
    db.add(
        Order(
            order_number="87654321",
            telegram_id=202,
            product_id=7,
            product_title="130 Coins",
            coins_amount=130,
            price_uzs=25000,
            status="REJECTED",
        )
    )
    db.commit()
    assert db.query(ReferralReward).filter(
        ReferralReward.reward_type == "FIRST_SHOP_COMPLETION"
    ).count() == 0
    assert Decimal(str(db.get(Wallet, 102).uzs_balance)) == Decimal("1000")
    assert referral_summary(db, 102)["coin_shop_buyers"] == 0


def test_referral_summary_requires_verified_telegram_user(monkeypatch):
    sessions = session_factory()
    db = sessions()
    add_user(db, 103)
    db.commit()
    db.close()
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", "test-token")
    app = FastAPI()
    app.include_router(referral_router)

    def dependency():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    assert client.get("/referrals/me").status_code == 401
    response = client.get(
        "/referrals/me",
        headers={"X-Telegram-Init-Data": init_data(103)},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_referrals"] == 0
    assert data["coin_shop_buyers"] == 0
    assert data["registration_bonus_uzs"] == 1000
    assert data["first_shop_bonus_uzs"] == 5000
    assert data["referral_link"].endswith(f"ref_{data['referral_code']}")
