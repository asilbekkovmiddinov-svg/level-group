from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_DOWN
import random

from sqlalchemy.orm import Session

from app.models.wheel import WheelSettings, WheelDailyLimit, WheelSpin, WheelCoinOrder
from app.crud.wallet import add_efc_balance, add_uzs_balance
from app.crud.transaction import create_transaction


SPIN_TYPE_FREE = "FREE"
SPIN_TYPE_AD = "AD"
SPIN_TYPE_BONUS = "BONUS"

REWARD_TYPE_NONE = "NONE"
REWARD_TYPE_EFC = "EFC"
REWARD_TYPE_UZS = "UZS"
REWARD_TYPE_COIN_ORDER = "COIN_ORDER"

STATUS_COMPLETED = "COMPLETED"
STATUS_WAITING_DETAILS = "WAITING_DETAILS"
STATUS_PENDING = "PENDING"
STATUS_REJECTED = "REJECTED"

MAX_AD_SPINS_PER_DAY = 10
FREE_COOLDOWN_HOURS = 24
AD_COOLDOWN_MINUTES = 60

EFC_250_INTERVAL_MIN = 8000
EFC_250_INTERVAL_MAX = 10000
EFC_500_INTERVAL_MIN = 18000
EFC_500_INTERVAL_MAX = 21000
UZS_1000_INTERVAL_MIN = 29000
UZS_1000_INTERVAL_MAX = 31000
UZS_5000_INTERVAL_MIN = 48000
UZS_5000_INTERVAL_MAX = 52000
COIN_130_INTERVAL_MIN = 65000
COIN_130_INTERVAL_MAX = 75000
JACKPOT_INTERVAL = 100000


BASE_REWARDS = [
    {"code": "lose", "type": REWARD_TYPE_NONE, "amount": Decimal("0"), "weight": 7500, "message": "❌ Bu safar yutuq chiqmadi."},
    {"code": "efc_50", "type": REWARD_TYPE_EFC, "amount": Decimal("50"), "weight": 1500, "message": "🪙 50 EFC yutdingiz!"},
    {"code": "efc_100", "type": REWARD_TYPE_EFC, "amount": Decimal("100"), "weight": 700, "message": "🔥 100 EFC yutdingiz!"},
    {"code": "uzs_500", "type": REWARD_TYPE_UZS, "amount": Decimal("500"), "weight": 300, "message": "💵 500 UZS yutdingiz!"},
]


def to_decimal(value):
    return Decimal(str(value))


def round_efc(value):
    return to_decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


def get_now():
    return datetime.utcnow()


def make_naive(dt):
    if not dt:
        return None
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


def get_today():
    return date.today()

def get_or_create_settings(db: Session):
    settings = db.query(WheelSettings).filter(WheelSettings.id == 1).first()

    if settings:
        return settings

    settings = WheelSettings(
        id=1,
        global_spin_count=0,
        next_130_coin_spin=random.randint(COIN_130_INTERVAL_MIN, COIN_130_INTERVAL_MAX),
        next_jackpot_spin=JACKPOT_INTERVAL,
        jackpot_coin_amount=2000,
        coin_130_amount=130,
        is_active=True,
    )

    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def get_or_create_daily_limit(db: Session, telegram_id: int):
    today = get_today()

    limit = db.query(WheelDailyLimit).filter(
        WheelDailyLimit.telegram_id == telegram_id,
        WheelDailyLimit.spin_date == today,
    ).first()

    if limit:
        return limit

    limit = WheelDailyLimit(
        telegram_id=telegram_id,
        spin_date=today,
        free_spin_used=False,
        ad_spin_count=0,
        bonus_spin_count=0,
        last_ad_spin_at=None,
    )

    db.add(limit)
    db.commit()
    db.refresh(limit)
    return limit


def format_utc(value):
    if value is None:
        return None
    return f"{make_naive(value).isoformat()}Z"


def get_cooldown_status(last_spin_at, cooldown: timedelta, now=None):
    current = make_naive(now or get_now())
    if not last_spin_at:
        return True, None, 1

    next_spin_at = make_naive(last_spin_at) + cooldown
    if current >= next_spin_at:
        return True, None, 1
    return False, format_utc(next_spin_at), 0


def get_last_free_spin_at(db: Session, telegram_id: int):
    spin = (
        db.query(WheelSpin)
        .filter(
            WheelSpin.telegram_id == telegram_id,
            WheelSpin.spin_type == SPIN_TYPE_FREE,
            WheelSpin.status == STATUS_COMPLETED,
        )
        .order_by(WheelSpin.created_at.desc())
        .first()
    )
    return spin.created_at if spin else None


def get_last_completed_spin(db: Session, telegram_id: int):
    return (
        db.query(WheelSpin)
        .filter(
            WheelSpin.telegram_id == telegram_id,
            WheelSpin.status == STATUS_COMPLETED,
        )
        .order_by(WheelSpin.created_at.desc(), WheelSpin.id.desc())
        .first()
    )


def serialize_last_win(spin):
    if spin is None:
        return None

    return {
        "reward_type": spin.reward_type,
        "reward_amount": float(spin.reward_amount),
        "reward_code": spin.reward_code,
        "created_at": format_utc(spin.created_at),
    }


def can_spin(limit: WheelDailyLimit, spin_type: str, last_free_spin_at=None, now=None):
    current = make_naive(now or get_now())

    if spin_type == SPIN_TYPE_FREE:
        available, next_spin_at, _remaining = get_cooldown_status(
            last_free_spin_at,
            timedelta(hours=FREE_COOLDOWN_HOURS),
            current,
        )
        if not available:
            return False, f"Keyingi bepul aylantirish: {next_spin_at}"
        return True, None

    if spin_type == SPIN_TYPE_AD:
        available, next_spin_at, _remaining = get_cooldown_status(
            limit.last_ad_spin_at,
            timedelta(minutes=AD_COOLDOWN_MINUTES),
            current,
        )
        if not available:
            return False, f"Keyingi reklama aylantirish: {next_spin_at}"
        return True, None

    if spin_type == SPIN_TYPE_BONUS:
        if limit.bonus_spin_count <= 0:
            return False, "Bonus aylantirish mavjud emas"
        return True, None

    return False, "Spin turi noto‘g‘ri"

def mark_spin_used(limit: WheelDailyLimit, spin_type: str):
    if spin_type == SPIN_TYPE_FREE:
        limit.free_spin_used = True
    elif spin_type == SPIN_TYPE_AD:
        limit.ad_spin_count += 1
        limit.last_ad_spin_at = get_now()
    elif spin_type == SPIN_TYPE_BONUS:
        limit.bonus_spin_count -= 1

def get_next_ad_spin_at(limit: WheelDailyLimit, now=None):
    return get_cooldown_status(
        limit.last_ad_spin_at,
        timedelta(minutes=AD_COOLDOWN_MINUTES),
        now,
    )[1]

def choose_base_reward():
    total_weight = sum(item["weight"] for item in BASE_REWARDS)
    ticket = random.randint(1, total_weight)
    current = 0

    for item in BASE_REWARDS:
        current += item["weight"]
        if ticket <= current:
            return item

    return BASE_REWARDS[0]


def should_give_interval_reward(current_spin: int, minimum: int, maximum: int):
    interval = random.randint(minimum, maximum)
    return current_spin % interval == 0


def make_reward(code: str, reward_type: str, amount, message: str):
    return {"code": code, "type": reward_type, "amount": Decimal(str(amount)), "message": message}


def choose_reward(settings: WheelSettings):
    current_spin = settings.global_spin_count + 1

    if current_spin % JACKPOT_INTERVAL == 0:
        settings.next_jackpot_spin = current_spin + JACKPOT_INTERVAL
        return make_reward("coin_2000_jackpot", REWARD_TYPE_COIN_ORDER, settings.jackpot_coin_amount, "👑 JACKPOT! 2000 Coin yutdingiz!")

    if current_spin >= settings.next_130_coin_spin:
        settings.next_130_coin_spin = current_spin + random.randint(COIN_130_INTERVAL_MIN, COIN_130_INTERVAL_MAX)
        return make_reward("coin_130", REWARD_TYPE_COIN_ORDER, settings.coin_130_amount, "🏆 130 Coin yutdingiz!")

    interval_rewards = (
        (UZS_5000_INTERVAL_MIN, UZS_5000_INTERVAL_MAX, "uzs_5000", REWARD_TYPE_UZS, 5000, "💵 5000 UZS yutdingiz!"),
        (UZS_1000_INTERVAL_MIN, UZS_1000_INTERVAL_MAX, "uzs_1000", REWARD_TYPE_UZS, 1000, "💵 1000 UZS yutdingiz!"),
        (EFC_500_INTERVAL_MIN, EFC_500_INTERVAL_MAX, "efc_500", REWARD_TYPE_EFC, 500, "💎 500 EFC yutdingiz!"),
        (EFC_250_INTERVAL_MIN, EFC_250_INTERVAL_MAX, "efc_250", REWARD_TYPE_EFC, 250, "⭐ 250 EFC yutdingiz!"),
    )
    for minimum, maximum, code, reward_type, amount, message in interval_rewards:
        if should_give_interval_reward(current_spin, minimum, maximum):
            return make_reward(code, reward_type, amount, message)

    return choose_base_reward()

def create_spin_record(db: Session, telegram_id: int, spin_type: str, reward: dict, global_spin_number: int):
    spin = WheelSpin(
        telegram_id=telegram_id,
        spin_type=spin_type,
        reward_code=reward["code"],
        reward_type=reward["type"],
        reward_amount=round_efc(reward["amount"]),
        global_spin_number=global_spin_number,
        status=STATUS_COMPLETED,
    )

    db.add(spin)
    db.commit()
    db.refresh(spin)
    return spin


def create_coin_order(db: Session, spin: WheelSpin, telegram_id: int, username, first_name, coin_amount: int):
    order = WheelCoinOrder(
        spin_id=spin.id,
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        coin_amount=coin_amount,
        status=STATUS_WAITING_DETAILS,
    )

    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def apply_reward(db: Session, telegram_id: int, reward: dict, spin: WheelSpin, limit: WheelDailyLimit, username=None, first_name=None):
    reward_type = reward["type"]
    amount = round_efc(reward["amount"])

    if reward_type == REWARD_TYPE_EFC:
        wallet = add_efc_balance(db=db, telegram_id=telegram_id, amount=amount)
        create_transaction(
            db=db,
            telegram_id=telegram_id,
            currency="EFC",
            amount=amount,
            balance_before=wallet.efc_balance - amount,
            balance_after=wallet.efc_balance,
            type="WHEEL_REWARD",
            description=f"Wheel yutug‘i: {amount} EFC",
        )

    elif reward_type == REWARD_TYPE_UZS:
        wallet = add_uzs_balance(db=db, telegram_id=telegram_id, amount=amount)
        create_transaction(
            db=db,
            telegram_id=telegram_id,
            currency="UZS",
            amount=amount,
            balance_before=wallet.uzs_balance - amount,
            balance_after=wallet.uzs_balance,
            type="WHEEL_REWARD",
            description=f"Wheel yutug‘i: {amount} UZS",
        )

    elif reward_type == REWARD_TYPE_COIN_ORDER:
        create_coin_order(db, spin, telegram_id, username, first_name, int(amount))


def spin_wheel(db: Session, telegram_id: int, spin_type: str, username=None, first_name=None):
    spin_type = spin_type.upper()
    settings = get_or_create_settings(db)

    if not settings.is_active:
        return {"success": False, "message": "Wheel hozircha faol emas"}

    limit = get_or_create_daily_limit(db, telegram_id)
    now = get_now()
    last_free_spin_at = (
        get_last_free_spin_at(db, telegram_id)
        if spin_type == SPIN_TYPE_FREE
        else None
    )
    allowed, error = can_spin(
        limit,
        spin_type,
        last_free_spin_at=last_free_spin_at,
        now=now,
    )

    if not allowed:
        return {"success": False, "message": error}

    reward = choose_reward(settings)
    settings.global_spin_count += 1
    global_spin_number = settings.global_spin_count
    mark_spin_used(limit, spin_type)

    db.commit()
    db.refresh(settings)
    db.refresh(limit)

    spin = create_spin_record(db, telegram_id, spin_type, reward, global_spin_number)
    apply_reward(db, telegram_id, reward, spin, limit, username, first_name)

    db.commit()
    db.refresh(limit)

    return {
        "success": True,
        "spin_id": spin.id,
        "reward_code": reward["code"],
        "reward_type": reward["type"],
        "reward_amount": float(reward["amount"]),
        "message": reward["message"],
        "global_spin_number": global_spin_number,
        "free_spin_used": limit.free_spin_used,
        "ad_spin_count": limit.ad_spin_count,
        "bonus_spin_count": limit.bonus_spin_count,
        "next_ad_spin_at": get_next_ad_spin_at(limit),
    }


def get_wheel_status(db: Session, telegram_id: int):
    limit = get_or_create_daily_limit(db, telegram_id)
    settings = get_or_create_settings(db)
    now = get_now()
    free_available, next_free_spin_at, remaining_free_spins = get_cooldown_status(
        get_last_free_spin_at(db, telegram_id),
        timedelta(hours=FREE_COOLDOWN_HOURS),
        now,
    )
    ad_available, next_ad_spin_at, remaining_ad_spins = get_cooldown_status(
        limit.last_ad_spin_at,
        timedelta(minutes=AD_COOLDOWN_MINUTES),
        now,
    )

    return {
        "success": True,
        "free_spin_available": free_available,
        "next_free_spin_at": next_free_spin_at,
        "remaining_free_spins": remaining_free_spins,
        "ad_spin_available": ad_available,
        "next_ad_spin_at": next_ad_spin_at,
        "remaining_ad_spins": remaining_ad_spins,
        "server_time": format_utc(now),
        "free_spin_used": limit.free_spin_used,
        "ad_spin_count": limit.ad_spin_count,
        "bonus_spin_count": limit.bonus_spin_count,
        "max_ad_spins": MAX_AD_SPINS_PER_DAY,
        "global_spin_count": settings.global_spin_count,
        "last_win": serialize_last_win(get_last_completed_spin(db, telegram_id)),
    }


def get_waiting_coin_order(db: Session, telegram_id: int):
    return db.query(WheelCoinOrder).filter(
        WheelCoinOrder.telegram_id == telegram_id,
        WheelCoinOrder.status == STATUS_WAITING_DETAILS,
    ).order_by(WheelCoinOrder.id.desc()).first()


def fill_coin_order_details(
    db: Session,
    telegram_id: int,
    spin_id: int,
    konami_login: str,
    konami_password: str,
    region: str,
    platform: str,
):
    order = (
        db.query(WheelCoinOrder)
        .filter(WheelCoinOrder.spin_id == spin_id)
        .with_for_update()
        .first()
    )
    if not order:
        return None
    if order.telegram_id != telegram_id:
        return "forbidden"
    if order.status != STATUS_WAITING_DETAILS:
        return "not_waiting"

    order.konami_login = konami_login
    order.konami_password = konami_password
    order.region = region
    order.device = platform
    order.status = STATUS_PENDING

    db.commit()
    db.refresh(order)
    return order


def get_pending_coin_orders(db: Session):
    return db.query(WheelCoinOrder).filter(WheelCoinOrder.status == STATUS_PENDING).order_by(WheelCoinOrder.id.asc()).all()


def get_coin_order(db: Session, order_id: int):
    return db.query(WheelCoinOrder).filter(WheelCoinOrder.id == order_id).first()


def approve_coin_order(db: Session, order_id: int, admin_id: int):
    order = get_coin_order(db, order_id)

    if not order:
        return None

    if order.status != STATUS_PENDING:
        return "not_pending"

    order.status = STATUS_COMPLETED
    order.admin_id = admin_id
    order.completed_at = get_now()

    db.commit()
    db.refresh(order)
    return order


def reject_coin_order(db: Session, order_id: int, admin_id: int, reason: str = "Admin rad etdi"):
    order = get_coin_order(db, order_id)

    if not order:
        return None

    if order.status != STATUS_PENDING:
        return "not_pending"

    order.status = STATUS_REJECTED
    order.admin_id = admin_id
    order.reject_reason = reason

    db.commit()
    db.refresh(order)
    return order
