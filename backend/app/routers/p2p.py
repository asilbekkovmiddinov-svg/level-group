from datetime import timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.p2p import (
    create_p2p_order,
    get_open_p2p_orders,
    get_p2p_order,
    cancel_p2p_order,
    create_p2p_trade,
    approve_p2p_trade,
    reject_p2p_trade,
    confirm_p2p_trade,
    get_my_p2p_orders,
    get_my_p2p_trades,
    get_my_active_p2p_trades,
    get_p2p_history,
    get_trade_remaining_time,
    check_all_p2p_timeouts,
    update_p2p_order_price,
    update_p2p_order_amount,
    update_p2p_order_min_trade,
    update_p2p_order_response_minutes,
)
from app.schemas.p2p import (
    P2PCreate,
    P2PCancel,
    P2PTradeCreate,
    P2PTradeAction,
    P2PUpdatePrice,
    P2PUpdateAmount,
    P2PUpdateMinTrade,
    P2PUpdateResponseMinutes,
)

router = APIRouter(
    prefix="/p2p",
    tags=["P2P"],
)

UZ_TZ = timezone(timedelta(hours=5))


def format_uz_datetime(dt):
    if not dt:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(UZ_TZ).strftime("%d.%m.%Y %H:%M:%S")


def order_response(order):
    return {
        "id": order.id,
        "owner_id": order.owner_id,
        "order_type": order.order_type,
        "efc_amount": float(order.efc_amount),
        "remaining_efc": float(order.remaining_efc),
        "price_uzs": float(order.price_uzs),
        "min_trade_efc": float(order.min_trade_efc),
        "response_minutes": order.response_minutes,
        "status": order.status,
        "created_at": format_uz_datetime(order.created_at),
        "updated_at": format_uz_datetime(order.updated_at),
        "completed_at": format_uz_datetime(order.completed_at),
        "cancelled_at": format_uz_datetime(order.cancelled_at),
        "cancel_reason": order.cancel_reason,
    }


def trade_response(trade):
    remaining_seconds, remaining_text = get_trade_remaining_time(trade)

    return {
        "id": trade.id,
        "order_id": trade.order_id,
        "owner_id": trade.owner_id,
        "requester_id": trade.requester_id,
        "order_type": trade.order_type,
        "efc_amount": float(trade.efc_amount),
        "price_uzs": float(trade.price_uzs),
        "total_uzs": float(trade.total_uzs),
        "efc_fee": float(trade.efc_fee),
        "uzs_fee": float(trade.uzs_fee),
        "owner_status": trade.owner_status,
        "requester_status": trade.requester_status,
        "status": trade.status,
        "response_minutes": trade.order.response_minutes if trade.order else 15,
        "expires_at": (
            trade.expires_at.isoformat()
            if trade.expires_at
            else None
        ),
        "owner_expires_at": (
            trade.owner_expires_at.isoformat()
            if trade.owner_expires_at
            else None
        ),
        "requester_expires_at": (
            trade.requester_expires_at.isoformat()
            if trade.requester_expires_at
            else None
        ),
        "remaining_seconds": remaining_seconds,
        "remaining_text": remaining_text,
        "timeout_stage": trade.timeout_stage,
        "cancel_reason": trade.cancel_reason,
        "created_at": format_uz_datetime(trade.created_at),
        "updated_at": format_uz_datetime(trade.updated_at),
        "approved_at": format_uz_datetime(trade.approved_at),
        "completed_at": format_uz_datetime(trade.completed_at),
        "rejected_at": format_uz_datetime(trade.rejected_at),
        "cancelled_at": format_uz_datetime(trade.cancelled_at),
        "timeout_at": format_uz_datetime(trade.timeout_at),
    }


@router.post("/timeouts/check")
def check_timeouts(db: Session = Depends(get_db)):
    trades = check_all_p2p_timeouts(db=db)

    return {
        "success": True,
        "message": "P2P timeout tekshirildi",
        "count": len(trades),
        "data": [trade_response(trade) for trade in trades],
    }


@router.post("/create")
def create_order(
    data: P2PCreate,
    db: Session = Depends(get_db),
):
    order = create_p2p_order(
        db=db,
        telegram_id=data.telegram_id,
        order_type=data.order_type,
        efc_amount=data.efc_amount,
        price_uzs=data.price_uzs,
        min_trade_efc=data.min_trade_efc,
        response_minutes=data.response_minutes,
    )

    if order == "invalid_order_type":
        return {"success": False, "message": "Order turi noto‘g‘ri"}

    if order == "invalid_response_minutes":
        return {"success": False, "message": "Javob vaqti noto‘g‘ri"}

    if order == "min_efc":
        return {"success": False, "message": "Minimal e’lon 50 EFC"}

    if order == "max_efc":
        return {"success": False, "message": "Maksimal e’lon 10000 EFC"}

    if order == "min_trade":
        return {
            "success": False,
            "message": "Minimal savdo 50 EFC dan kam bo‘lmaydi",
        }

    if order == "insufficient_efc":
        return {"success": False, "message": "EFC balans yetarli emas"}

    if order == "insufficient_uzs":
        return {"success": False, "message": "UZS balans yetarli emas"}

    if not order:
        return {"success": False, "message": "P2P e’lon yaratilmadi"}

    return {
        "success": True,
        "message": "P2P e’lon yaratildi",
        "data": order_response(order),
    }


@router.get("/open")
def open_orders(
    order_type: str | None = None,
    db: Session = Depends(get_db),
):
    orders = get_open_p2p_orders(db=db, order_type=order_type)

    return {
        "success": True,
        "data": [order_response(order) for order in orders],
    }


@router.get("/my/{telegram_id}")
def my_orders(
    telegram_id: int,
    db: Session = Depends(get_db),
):
    orders = get_my_p2p_orders(db=db, telegram_id=telegram_id)

    return {
        "success": True,
        "data": [order_response(order) for order in orders],
    }


@router.get("/trades/my/{telegram_id}")
def my_trades(
    telegram_id: int,
    active_only: bool = False,
    db: Session = Depends(get_db),
):
    if active_only:
        trades = get_my_active_p2p_trades(db=db, telegram_id=telegram_id)
    else:
        trades = get_my_p2p_trades(db=db, telegram_id=telegram_id)

    return {
        "success": True,
        "data": [trade_response(trade) for trade in trades],
    }


@router.get("/history/{telegram_id}")
def my_history(
    telegram_id: int,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    trades = get_p2p_history(
        db=db,
        telegram_id=telegram_id,
        status=status,
    )

    return {
        "success": True,
        "data": [trade_response(trade) for trade in trades],
    }


@router.get("/{order_id}")
def one_order(
    order_id: int,
    db: Session = Depends(get_db),
):
    order = get_p2p_order(db, order_id)

    if not order:
        return {"success": False, "message": "P2P e’lon topilmadi"}

    return {
        "success": True,
        "data": order_response(order),
    }


@router.post("/{order_id}/trade")
def create_trade(
    order_id: int,
    data: P2PTradeCreate,
    db: Session = Depends(get_db),
):
    trade = create_p2p_trade(
        db=db,
        order_id=order_id,
        telegram_id=data.telegram_id,
        efc_amount=data.efc_amount,
    )

    if trade == "not_open":
        return {"success": False, "message": "E’lon ochiq emas"}

    if trade == "own_order":
        return {
            "success": False,
            "message": "O‘zingizning e’loningiz bilan savdo qila olmaysiz",
        }

    if trade == "min_trade":
        return {
            "success": False,
            "message": "Minimal savdo miqdori yetarli emas",
        }

    if trade == "too_much":
        return {"success": False, "message": "E’londa yetarli EFC qolmagan"}

    if trade == "insufficient_efc":
        return {"success": False, "message": "EFC balans yetarli emas"}

    if trade == "insufficient_uzs":
        return {"success": False, "message": "UZS balans yetarli emas"}

    if not trade:
        return {"success": False, "message": "Savdo so‘rovi yaratilmadi"}

    return {
        "success": True,
        "message": "Savdo so‘rovi yuborildi",
        "data": trade_response(trade),
    }


@router.post("/trade/{trade_id}/approve")
def approve_trade(
    trade_id: int,
    data: P2PTradeAction,
    db: Session = Depends(get_db),
):
    trade = approve_p2p_trade(
        db=db,
        trade_id=trade_id,
        telegram_id=data.telegram_id,
    )

    if trade == "timeout":
        return {"success": False, "message": "Savdo vaqti tugagan"}

    if trade == "not_owner":
        return {"success": False, "message": "Faqat e’lon egasi tasdiqlaydi"}

    if trade == "not_pending":
        return {"success": False, "message": "Savdo kutilayotgan holatda emas"}

    if not trade:
        return {"success": False, "message": "Savdo topilmadi"}

    return {
        "success": True,
        "message": "Savdo e’lon egasi tomonidan tasdiqlandi",
        "data": trade_response(trade),
    }


@router.post("/trade/{trade_id}/reject")
def reject_trade(
    trade_id: int,
    data: P2PTradeAction,
    db: Session = Depends(get_db),
):
    trade = reject_p2p_trade(
        db=db,
        trade_id=trade_id,
        telegram_id=data.telegram_id,
    )

    if trade == "timeout":
        return {"success": False, "message": "Savdo vaqti tugagan"}

    if trade == "not_owner":
        return {"success": False, "message": "Faqat e’lon egasi rad etadi"}

    if trade == "not_pending":
        return {"success": False, "message": "Savdo kutilayotgan holatda emas"}

    if not trade:
        return {"success": False, "message": "Savdo topilmadi"}

    return {
        "success": True,
        "message": "Savdo rad etildi",
        "data": trade_response(trade),
    }


@router.post("/trade/{trade_id}/confirm")
def confirm_trade(
    trade_id: int,
    data: P2PTradeAction,
    db: Session = Depends(get_db),
):
    trade = confirm_p2p_trade(
        db=db,
        trade_id=trade_id,
        telegram_id=data.telegram_id,
    )

    if trade == "timeout":
        return {"success": False, "message": "Savdo vaqti tugagan"}

    if trade == "not_requester":
        return {
            "success": False,
            "message": "Faqat savdo boshlagan foydalanuvchi yakuniy tasdiqlaydi",
        }

    if trade == "not_approved":
        return {
            "success": False,
            "message": "Savdo hali e’lon egasi tomonidan tasdiqlanmagan",
        }

    if trade == "too_much":
        return {"success": False, "message": "E’londa yetarli EFC qolmagan"}

    if trade == "insufficient_efc":
        return {"success": False, "message": "EFC balans yetarli emas"}

    if trade == "insufficient_uzs":
        return {"success": False, "message": "UZS balans yetarli emas"}

    if not trade:
        return {"success": False, "message": "Savdo topilmadi"}

    return {
        "success": True,
        "message": "P2P savdo yakunlandi",
        "data": trade_response(trade),
    }


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    data: P2PCancel,
    db: Session = Depends(get_db),
):
    order = cancel_p2p_order(
        db=db,
        order_id=order_id,
        telegram_id=data.telegram_id,
    )

    if order == "not_owner":
        return {
            "success": False,
            "message": "Faqat e’lon egasi bekor qila oladi",
        }

    if order == "cannot_cancel":
        return {
            "success": False,
            "message": "Bu e’lonni bekor qilib bo‘lmaydi",
        }

    if order == "has_pending_trade":
        return {
            "success": False,
            "message": "Aktiv savdo bor. Avval uni yakunlang yoki rad eting",
        }

    if not order:
        return {"success": False, "message": "P2P e’lon topilmadi"}

    return {
        "success": True,
        "message": "P2P e’lon bekor qilindi",
        "data": order_response(order),
    }


@router.post("/{order_id}/update-price")
def update_order_price(
    order_id: int,
    data: P2PUpdatePrice,
    db: Session = Depends(get_db),
):
    order = update_p2p_order_price(
        db=db,
        order_id=order_id,
        telegram_id=data.telegram_id,
        price_uzs=data.price_uzs,
    )

    if order == "not_owner":
        return {
            "success": False,
            "message": "Faqat e’lon egasi narxni o‘zgartira oladi",
        }

    if order == "cannot_update":
        return {
            "success": False,
            "message": "Bu e’lon narxini o‘zgartirib bo‘lmaydi",
        }

    if order == "invalid_price":
        return {"success": False, "message": "Narx noto‘g‘ri"}

    if order == "insufficient_uzs":
        return {"success": False, "message": "UZS balans yetarli emas"}

    if order == "has_pending_trade":
        return {
            "success": False,
            "message": "Aktiv savdo so‘rovi bor. Avval uni yakunlang yoki rad eting",
        }

    if not order:
        return {"success": False, "message": "P2P e’lon topilmadi"}

    return {
        "success": True,
        "message": "P2P e’lon narxi yangilandi",
        "data": order_response(order),
    }


@router.post("/{order_id}/update-amount")
def update_order_amount(
    order_id: int,
    data: P2PUpdateAmount,
    db: Session = Depends(get_db),
):
    order = update_p2p_order_amount(
        db=db,
        order_id=order_id,
        telegram_id=data.telegram_id,
        efc_amount=data.efc_amount,
    )

    if order == "not_owner":
        return {
            "success": False,
            "message": "Faqat e’lon egasi miqdorni o‘zgartira oladi",
        }

    if order == "cannot_update":
        return {
            "success": False,
            "message": "Bu e’lon miqdorini o‘zgartirib bo‘lmaydi",
        }

    if order == "has_pending_trade":
        return {
            "success": False,
            "message": "Aktiv savdo bor. Avval uni yakunlang yoki rad eting",
        }

    if order == "min_efc":
        return {"success": False, "message": "Minimal e’lon 50 EFC"}

    if order == "max_efc":
        return {"success": False, "message": "Maksimal e’lon 10000 EFC"}

    if order == "less_than_sold":
        return {
            "success": False,
            "message": "Miqdor sotilgan EFC dan kam bo‘la olmaydi",
        }

    if order == "insufficient_efc":
        return {"success": False, "message": "EFC balans yetarli emas"}

    if order == "insufficient_uzs":
        return {"success": False, "message": "UZS balans yetarli emas"}

    if not order:
        return {"success": False, "message": "P2P e’lon topilmadi"}

    return {
        "success": True,
        "message": "P2P e’lon miqdori yangilandi",
        "data": order_response(order),
    }


@router.post("/{order_id}/update-min-trade")
def update_order_min_trade(
    order_id: int,
    data: P2PUpdateMinTrade,
    db: Session = Depends(get_db),
):
    order = update_p2p_order_min_trade(
        db=db,
        order_id=order_id,
        telegram_id=data.telegram_id,
        min_trade_efc=data.min_trade_efc,
    )

    if order == "not_owner":
        return {
            "success": False,
            "message": "Faqat e’lon egasi minimal savdoni o‘zgartira oladi",
        }

    if order == "cannot_update":
        return {
            "success": False,
            "message": "Bu e’lonni o‘zgartirib bo‘lmaydi",
        }

    if order == "min_trade":
        return {"success": False, "message": "Minimal savdo noto‘g‘ri"}

    if not order:
        return {"success": False, "message": "P2P e’lon topilmadi"}

    return {
        "success": True,
        "message": "Minimal savdo yangilandi",
        "data": order_response(order),
    }


@router.post("/{order_id}/update-response-minutes")
def update_order_response_minutes(
    order_id: int,
    data: P2PUpdateResponseMinutes,
    db: Session = Depends(get_db),
):
    order = update_p2p_order_response_minutes(
        db=db,
        order_id=order_id,
        telegram_id=data.telegram_id,
        response_minutes=data.response_minutes,
    )

    if order == "not_owner":
        return {
            "success": False,
            "message": "Faqat e’lon egasi javob vaqtini o‘zgartira oladi",
        }

    if order == "cannot_update":
        return {
            "success": False,
            "message": "Bu e’lonni o‘zgartirib bo‘lmaydi",
        }

    if order == "invalid_response_minutes":
        return {"success": False, "message": "Javob vaqti noto‘g‘ri"}

    if not order:
        return {"success": False, "message": "P2P e’lon topilmadi"}

    return {
        "success": True,
        "message": "Javob vaqti yangilandi",
        "data": order_response(order),
        }
