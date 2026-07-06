from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_DOWN
import random

from sqlalchemy.orm import Session

from app.models.wheel import WheelSettings, WheelDailyLimit, WheelSpin, WheelCoinOrder
from app.crud.wallet import add_efc_balance
from app.crud.transaction import create_transaction


SPIN_TYPE_FREE = "FREE"
SPIN_TYPE_AD = "AD"
SPIN_TYPE_BONUS = "BONUS"

REWARD_TYPE_NONE = "NONE"
REWARD_TYPE_EFC = "EFC"
REWARD_TYPE_BONUS_SPIN = "BONUS_SPIN"
REWARD_TYPE_COIN_ORDER = "COIN_ORDER"

STATUS_COMPLETED = "COMPLETED"
STATUS_WAITING_DETAILS = "WAITING_DETAILS"
STATUS_PENDING = "PENDING"
STATUS_REJECTED = "REJECTED"

MAX_AD_SPINS_PER_DAY = 10
AD_COOLDOWN_MINUTES = 60

SUPER_EFC_INTERVAL_MIN = 9000
SUPER_EFC_INTERVAL_MAX = 11000
COIN_130_INTERVAL_MIN = 1
COIN_130_INTERVAL_MAX = 2
JACKPOT_INTERVAL_MIN = 98000
JACKPOT_INTERVAL_MAX = 102000


BASE_REWARDS = [
    {"code": "lose", "type": REWARD_TYPE_NONE, "amount": Decimal("0"), "weight": 4500, "message": "❌ Bu safar yutuq chiqmadi."},
    {"code": "bonus_spin", "type": REWARD_TYPE_BONUS_SPIN, "amount": Decimal("1"), "weight": 1000, "message": "🎁 Yana 1 marta bepul aylantirish yutdingiz!"},
    {"code": "efc_5", "type": REWARD_TYPE_EFC, "amount": Decimal("5"), "weight": 2200, "message": "🪙 5 EFC yutdingiz!"},
    {"code": "efc_10", "type": REWARD_TYPE_EFC, "amount": Decimal("10"), "weight": 1200, "message": "🪙 10 EFC yutdingiz!"},
    {"code": "efc_25", "type": REWARD_TYPE_EFC, "amount": Decimal("25"), "weight": 700, "message": "🪙 25 EFC yutdingiz!"},
    {"code": "efc_50", "type": REWARD_TYPE_EFC, "amount": Decimal("50"), "weight": 300, "message": "🪙 50 EFC yutdingiz!"},
    {"code": "efc_100", "type": REWARD_TYPE_EFC, "amount": Decimal("100"), "weight": 100, "message": "🔥 100 EFC yutdingiz!"},
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
        next_jackpot_spin=random.randint(JACKPOT_INTERVAL_MIN, JACKPOT_INTERVAL_MAX),
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


def can_spin(limit: WheelDailyLimit, spin_type: str):
    now = get_now()

    if spin_type == SPIN_TYPE_FREE:
        if limit.free_spin_used:
            return False, "Bugungi bepul aylantirish ishlatilgan"
        return True, None

    if spin_type == SPIN_TYPE_AD:
        if limit.ad_spin_count >= MAX_AD_SPINS_PER_DAY:
            return False, "Bugungi reklama aylantirish limiti tugagan"

        if limit.last_ad_spin_at:
            last_ad_spin_at = make_naive(limit.last_ad_spin_at)
            next_time = last_ad_spin_at + timedelta(minutes=AD_COOLDOWN_MINUTES)

            if now < next_time:
                seconds = int((next_time - now).total_seconds())
                minutes = seconds // 60
                return False, f"Keyingi reklama aylantirish: {minutes} daqiqadan keyin"

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

def add_bonus_spin(limit: WheelDailyLimit):
    limit.bonus_spin_count += 1


def get_next_ad_spin_at(limit: WheelDailyLimit):
    if not limit.last_ad_spin_at:
        return None

    last_ad_spin_at = make_naive(limit.last_ad_spin_at)
    next_time = last_ad_spin_at + timedelta(minutes=AD_COOLDOWN_MINUTES)

    if get_now() >= next_time:
        return None

    return next_time.isoformat()


def choose_base_reward():
    total_weight = sum(item["weight"] for item in BASE_REWARDS)
    ticket = random.randint(1, total_weight)
    current = 0

    for item in BASE_REWARDS:
        current += item["weight"]
        if ticket <= current:
            return item

    return BASE_REWARDS[0]


def should_give_super_efc(current_spin: int):
    interval = random.randint(SUPER_EFC_INTERVAL_MIN, SUPER_EFC_INTERVAL_MAX)
    return current_spin % interval == 0


def choose_reward(settings: WheelSettings):
    current_spin = settings.global_spin_count + 1

    if current_spin >= settings.next_jackpot_spin:
        settings.next_jackpot_spin = current_spin + random.randint(
            JACKPOT_INTERVAL_MIN,
            JACKPOT_INTERVAL_MAX,
        )
        return {
            "code": "coin_2000_jackpot",
            "type": REWARD_TYPE_COIN_ORDER,
            "amount": Decimal(str(settings.jackpot_coin_amount)),
            "message": "👑 JACKPOT! 2000 coin yutdingiz!",
        }

    if current_spin >= settings.next_130_coin_spin:
        settings.next_130_coin_spin = current_spin + random.randint(
            COIN_130_INTERVAL_MIN,
            COIN_130_INTERVAL_MAX,
        )
        return {
            "code": "coin_130",
            "type": REWARD_TYPE_COIN_ORDER,
            "amount": Decimal(str(settings.coin_130_amount)),
            "message": "🏆 130 coin yutdingiz!",
        }

    if should_give_super_efc(current_spin):
        return {
            "code": "efc_250",
            "type": REWARD_TYPE_EFC,
            "amount": Decimal("250"),
            "message": "⭐ 250 EFC yutdingiz!",
        }

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

    elif reward_type == REWARD_TYPE_BONUS_SPIN:
        add_bonus_spin(limit)

    elif reward_type == REWARD_TYPE_COIN_ORDER:
        create_coin_order(db, spin, telegram_id, username, first_name, int(amount))


def spin_wheel(db: Session, telegram_id: int, spin_type: str, username=None, first_name=None):
    spin_type = spin_type.upper()
    settings = get_or_create_settings(db)

    if not settings.is_active:
        return {"success": False, "message": "Wheel hozircha faol emas"}

    limit = get_or_create_daily_limit(db, telegram_id)
    allowed, error = can_spin(limit, spin_type)

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

    return {
        "success": True,
        "free_spin_used": limit.free_spin_used,
        "ad_spin_count": limit.ad_spin_count,
        "bonus_spin_count": limit.bonus_spin_count,
        "max_ad_spins": MAX_AD_SPINS_PER_DAY,
        "next_ad_spin_at": get_next_ad_spin_at(limit),
        "global_spin_count": settings.global_spin_count,
    }


def get_waiting_coin_order(db: Session, telegram_id: int):
    return db.query(WheelCoinOrder).filter(
        WheelCoinOrder.telegram_id == telegram_id,
        WheelCoinOrder.status == STATUS_WAITING_DETAILS,
    ).order_by(WheelCoinOrder.id.desc()).first()


def fill_coin_order_details(db: Session, telegram_id: int, konami_login: str, konami_password: str, region: str, device: str):
    order = get_waiting_coin_order(db, telegram_id)

    if not order:
        return None

    order.konami_login = konami_login
    order.konami_password = konami_password
    order.region = region
    order.device = device
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
