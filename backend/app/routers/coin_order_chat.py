from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.crud.coin_order_chat import (
    active_orders, add_message, apply_operator_action, get_coin_order, get_coin_order_for_update,
    list_messages, mark_read, normalize_order_type, unread_count,
)
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.coin_order_chat import CoinOrderMessageCreate, OperatorChatAction, OperatorMessageCreate
from app.models.coin_order_message import CoinOrderMessage
from app.crud.wheel import claim_coin_order, approve_coin_order, reject_coin_order

router = APIRouter(prefix="/coin-order-chat", tags=["Coin Order Chat"])
TERMINAL_STATUSES = {"COMPLETED", "REJECTED", "CANCELLED"}


def credential_operator(order_type, order):
    return order.admin_id


def message_response(item):
    return {"id": item.id, "order_type": item.order_type, "order_id": item.order_id,
            "sender": item.sender, "message": item.message, "created_at": item.created_at,
            "read_at": item.read_at}


def user_order(db, order_type, order_id, telegram_id):
    if not normalize_order_type(order_type): raise HTTPException(404, "Order not found")
    order = get_coin_order(db, order_type, order_id)
    if not order: raise HTTPException(404, "Order not found")
    if order.telegram_id != telegram_id: raise HTTPException(403, "Order belongs to another user")
    return order


@router.get("/{order_type}/{order_id}/messages")
def user_messages(order_type: str, order_id: int, current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    order = user_order(db, order_type, order_id, current_user.telegram_id)
    return {"success": True, "status": order.status,
            "unread_count": unread_count(db, order_type, order_id, "USER"),
            "data": [message_response(x) for x in list_messages(db, order_type, order_id)]}


@router.post("/{order_type}/{order_id}/messages")
def user_send(order_type: str, order_id: int, data: CoinOrderMessageCreate, current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    order = user_order(db, order_type, order_id, current_user.telegram_id)
    if order.status != "WAITING_OTP": raise HTTPException(409, "OTP input is not available")
    if not (data.message.isdigit() and len(data.message) == 6): raise HTTPException(400, "OTP must contain 6 digits")
    item = add_message(db, order_type, order, "USER", current_user.telegram_id, data.message)
    return {"success": True, "status": order.status, "data": message_response(item)}


@router.post("/{order_type}/{order_id}/read")
def user_read(order_type: str, order_id: int, current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    user_order(db, order_type, order_id, current_user.telegram_id)
    return {"success": True, "read": mark_read(db, order_type, order_id, "USER")}


@router.get("/internal/active")
def admin_active(_: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    return {"success": True, "data": [{"order_type": kind, "order_id": order.id,
            "telegram_id": order.telegram_id, "status": order.status,
            "coin_amount": getattr(order, "coin_amount", getattr(order, "coins_amount", None)),
            "unread_count": unread} for kind, order, unread in active_orders(db)]}


@router.get("/internal/{order_type}/{order_id}/messages")
def admin_messages(order_type: str, order_id: int, _: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    order = get_coin_order(db, order_type, order_id)
    if not order: raise HTTPException(404, "Order not found")
    return {"success": True, "status": order.status, "telegram_id": order.telegram_id,
            "coin_amount": getattr(order, "coins_amount", getattr(order, "coin_amount", None)),
            "operator_id": credential_operator(normalize_order_type(order_type), order),
            "completed_at": str(getattr(order, "completed_at", None) or "") or None,
            "rejected_at": str(getattr(order, "rejected_at", None) or "") or None,
            "data": [message_response(x) for x in list_messages(db, order_type, order_id)]}


@router.post("/internal/{order_type}/{order_id}/messages")
def admin_send(order_type: str, order_id: int, data: OperatorMessageCreate, _: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    order = get_coin_order(db, order_type, order_id)
    if not order: raise HTTPException(404, "Order not found")
    item = add_message(db, order_type, order, "OPERATOR", data.admin_id, data.message)
    return {"success": True, "status": order.status, "data": message_response(item)}


@router.post("/internal/{order_type}/{order_id}/read")
def admin_read(order_type: str, order_id: int, _: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    if not get_coin_order(db, order_type, order_id): raise HTTPException(404, "Order not found")
    return {"success": True, "read": mark_read(db, order_type, order_id, "OPERATOR")}


@router.post("/internal/{order_type}/{order_id}/action")
def admin_action(order_type: str, order_id: int, data: OperatorChatAction, _: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    order = get_coin_order_for_update(db, order_type, order_id)
    if not order: raise HTTPException(404, "Order not found")
    action = data.action.upper(); kind = normalize_order_type(order_type)
    if action in {"CLAIM", "COMPLETE", "REJECT"}:
        if action == "CLAIM":
            assigned = credential_operator(kind, order)
            if assigned is not None and assigned != data.admin_id:
                raise HTTPException(403, "Order belongs to another operator")
        funcs = {
            "WHEEL": {"CLAIM": lambda: claim_coin_order(db, order_id, data.admin_id),
                      "COMPLETE": lambda: approve_coin_order(db, order_id, data.admin_id),
                      "REJECT": lambda: reject_coin_order(db, order_id, data.admin_id, "Operator rad etdi")},
        }
        result = funcs[kind][action]()
        if not result or isinstance(result, str): raise HTTPException(409, "Action is invalid for current status")
        order = result
    else:
        if action == "OTP_SENT":
            from app.services.coin_order_notifications import otp_notification_retryable
        otp_retry = action == "OTP_SENT" and order.status == "WAITING_OTP" and otp_notification_retryable(order)
        if not otp_retry and not apply_operator_action(order, action, data.admin_id):
            raise HTTPException(409, "Action is invalid for current status")
        if action == "OTP_SENT" and not otp_retry:
            from app.crud.coin_order_chat import OTP_SENT_MESSAGE
            from app.models.coin_order_message import CoinOrderMessage
            db.add(CoinOrderMessage(order_type=kind, order_id=order.id, telegram_id=order.telegram_id,
                sender="SYSTEM", sender_id=data.admin_id, message=OTP_SENT_MESSAGE))
        db.commit(); db.refresh(order)
        if action == "OTP_SENT":
            from app.services.coin_order_notifications import send_coin_otp_user_notification
            notification = send_coin_otp_user_notification(db, kind, order.id)
            return {"success": True, "status": order.status, "notification_status": notification.status}
    return {"success": True, "status": order.status}
