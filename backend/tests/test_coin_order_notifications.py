from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.order import Order
from app.models.user import User
from app.models.wheel import WheelCoinOrder, WheelSpin
from app.services import coin_order_notifications


def sessions():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[User.__table__, Order.__table__, WheelSpin.__table__, WheelCoinOrder.__table__])
    return sessionmaker(bind=engine)


def test_shop_and_wheel_notify_once_after_waiting_otp(monkeypatch):
    factory = sessions()
    db = factory()
    db.add(User(telegram_id=42, first_name="Ali", username="ali"))
    db.add(Order(id=10, telegram_id=42, product_id=1, product_title="130 Coin", coins_amount=130,
        price_uzs=Decimal("1000"), platform="ANDROID", region="GLOBAL", status="WAITING_OPERATOR"))
    db.add(WheelSpin(id=20, telegram_id=42, spin_type="FREE", reward_code="coin_2000",
        reward_type="COIN_ORDER", reward_amount=2000, global_spin_number=1, status="COMPLETED"))
    db.flush()
    db.add(WheelCoinOrder(id=30, spin_id=20, telegram_id=42, username="ali", coin_amount=2000,
        device="IOS", region="JAPAN", status="WAITING_OPERATOR"))
    db.commit()

    sent = []
    def telegram(text, reply_markup=None, chat_id=None):
        sent.append((text, reply_markup))
        return type("Result", (), {"message_id": 900 + len(sent)})()
    monkeypatch.setattr(coin_order_notifications, "send_admin_message", telegram)

    assert coin_order_notifications.send_coin_order_notification(db, "SHOP", 10).sent is True
    assert coin_order_notifications.send_coin_order_notification(db, "WHEEL", 30).sent is True
    assert coin_order_notifications.send_coin_order_notification(db, "SHOP", 10).sent is False
    assert coin_order_notifications.send_coin_order_notification(db, "WHEEL", 30).sent is False
    assert len(sent) == 2
    assert "Order ID: #10" in sent[0][0] and "Manba: SHOP" in sent[0][0]
    assert "Coin: 2000" in sent[1][0] and "Manba: WHEEL" in sent[1][0]
    assert sent[0][1]["inline_keyboard"][0][0] == {
        "text": "💬 Buyurtmani ochish", "callback_data": "coinchatopen:SHOP:10",
    }
    assert sent[1][1]["inline_keyboard"][0][0]["callback_data"] == "coinchatopen:WHEEL:30"
    assert db.get(Order, 10).coin_notification_status == "SENT"
    assert db.get(WheelCoinOrder, 30).coin_notification_status == "SENT"
    db.close()


def test_rollback_or_non_waiting_order_never_notifies(monkeypatch):
    factory = sessions()
    db = factory()
    db.add(User(telegram_id=42, first_name="Ali"))
    db.add(Order(id=11, telegram_id=42, product_id=1, product_title="130 Coin", coins_amount=130,
        price_uzs=Decimal("1000"), platform="ANDROID", region="GLOBAL", status="PENDING"))
    db.commit()
    called = []
    monkeypatch.setattr(coin_order_notifications, "send_admin_message", lambda *args, **kwargs: called.append(True))
    result = coin_order_notifications.send_coin_order_notification(db, "SHOP", 11)
    assert result.status == "SKIPPED" and called == []
    db.close()


def test_routes_dispatch_only_after_crud_returns_committed_order():
    from pathlib import Path
    root = Path(__file__).parents[1] / "app" / "routers"
    shop = (root / "order.py").read_text()
    wheel = (root / "wheel.py").read_text()
    assert 'send_coin_order_notification(db, "SHOP", order.id)' in shop
    assert 'send_coin_order_notification(db, "WHEEL", order.id)' in wheel


def test_otp_user_notification_targets_exact_order_chat(monkeypatch):
    sent = []
    monkeypatch.setattr(coin_order_notifications.config, "COIN_MINIAPP_URL", "https://mini.example/app/")
    monkeypatch.setattr(coin_order_notifications, "send_admin_message",
        lambda text, reply_markup=None, chat_id=None: sent.append((text, reply_markup, chat_id)))

    result = coin_order_notifications.send_coin_otp_user_notification("WHEEL", 30, 42)

    assert result.sent is True
    assert sent[0][2] == 42
    assert "6 xonali kodni Order Chat ichiga yuboring" in sent[0][0]
    button = sent[0][1]["inline_keyboard"][0][0]
    assert button["text"] == "💬 Buyurtma suhbatini ochish"
    assert button["web_app"]["url"] == (
        "https://mini.example/app?coin_order_type=WHEEL&coin_order_id=30"
    )
