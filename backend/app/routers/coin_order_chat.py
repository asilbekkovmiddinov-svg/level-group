from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.crud.coin_order_chat import (
    active_orders, add_message, apply_operator_action, get_coin_order,
    list_messages, mark_read, normalize_order_type, unread_count,
)
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.coin_order_chat import CoinOrderMessageCreate, OperatorChatAction, OperatorMessageCreate
from app.crud.order import claim_order, approve_order, reject_order
from app.crud.wheel import claim_coin_order, approve_coin_order, reject_coin_order
from app.services.coin_credentials import decrypt_credential

router = APIRouter(prefix="/coin-order-chat", tags=["Coin Order Chat"])


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
    if order.status in {"COMPLETED", "REJECTED", "CANCELLED"}: raise HTTPException(409, "Order chat is closed")
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
    return {"success": True, "status": order.status,
            "data": [message_response(x) for x in list_messages(db, order_type, order_id)]}


@router.get("/internal/{order_type}/{order_id}/credentials")
def admin_credentials(order_type: str, order_id: int, _: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    order = get_coin_order(db, order_type, order_id)
    if not order: raise HTTPException(404, "Order not found")
    return {"success": True, "data": {"konami_login": getattr(order, "konami_login", None),
            "konami_password": decrypt_credential(getattr(order, "konami_password_encrypted", None)),
            "platform": getattr(order, "platform", getattr(order, "device", None)),
            "region": getattr(order, "region", None)}}


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
    order = get_coin_order(db, order_type, order_id)
    if not order: raise HTTPException(404, "Order not found")
    action = data.action.upper(); kind = normalize_order_type(order_type)
    if action in {"CLAIM", "COMPLETE", "REJECT"}:
        funcs = {
            "SHOP": {"CLAIM": lambda: claim_order(db, order_id, data.admin_id),
                     "COMPLETE": lambda: approve_order(db, order_id, data.admin_id),
                     "REJECT": lambda: reject_order(db, order_id, data.admin_id, "Operator rad etdi")},
            "WHEEL": {"CLAIM": lambda: claim_coin_order(db, order_id, data.admin_id),
                      "COMPLETE": lambda: approve_coin_order(db, order_id, data.admin_id),
                      "REJECT": lambda: reject_coin_order(db, order_id, data.admin_id, "Operator rad etdi")},
        }
        result = funcs[kind][action]()
        if not result or isinstance(result, str): raise HTTPException(409, "Action is invalid for current status")
        order = result
    else:
        if not apply_operator_action(order, action, data.admin_id): raise HTTPException(409, "Action is invalid for current status")
        db.commit(); db.refresh(order)
    return {"success": True, "status": order.status}
