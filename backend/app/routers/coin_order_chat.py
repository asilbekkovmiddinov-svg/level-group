from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from html import escape
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user, verify_init_data
from app.crud.coin_order_chat import (
    active_orders, add_message, apply_operator_action, get_coin_order, get_coin_order_for_update,
    list_messages, mark_read, normalize_order_type, unread_count,
)
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.coin_order_chat import CoinOrderDetailsCreate, CoinOrderMessageCreate, CredentialOpenRequest, OperatorChatAction, OperatorMessageCreate
from app.crud.coin_credentials import (
    consume_access_grant, create_access_grant, get_consumed_access_grant,
    open_credentials, record_credential_access_event,
)
from app.crud.coin_credentials import store_credentials
from app.models.coin_order_message import CoinOrderMessage
from app.crud.order import claim_order, approve_order, reject_order
from app.crud.wheel import claim_coin_order, approve_coin_order, reject_coin_order

router = APIRouter(prefix="/coin-order-chat", tags=["Coin Order Chat"])
TERMINAL_STATUSES = {"COMPLETED", "REJECTED", "CANCELLED"}
AUDIT_ACTIONS = {"EMAIL_COPY", "PASSWORD_REVEAL", "PASSWORD_COPY"}


def credential_operator(order_type, order):
    return order.claimed_by if order_type == "SHOP" else order.admin_id


def require_credential_operator(order_type, order, admin_id, assign=False):
    assigned = credential_operator(order_type, order)
    if assigned is None and assign:
        if order_type == "SHOP": order.claimed_by = admin_id
        else: order.admin_id = admin_id
    elif assigned != admin_id:
        raise HTTPException(403, "Credentials belong to another operator")


def credential_headers(script=False):
    scripts = "script-src https://telegram.org 'unsafe-inline'; connect-src 'self'; " if script else ""
    return {"Cache-Control":"no-store, private, max-age=0", "Pragma":"no-cache",
            "Referrer-Policy":"no-referrer", "X-Content-Type-Options":"nosniff",
            "X-Frame-Options":"SAMEORIGIN", "Content-Security-Policy":
            f"default-src 'none'; {scripts}style-src 'unsafe-inline'; form-action 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org"}


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


@router.post("/{order_type}/{order_id}/details")
def user_details(order_type: str, order_id: int, data: CoinOrderDetailsCreate,
    current_user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    kind = normalize_order_type(order_type)
    if kind != "SHOP": raise HTTPException(404, "Order not found")
    order = get_coin_order_for_update(db, kind, order_id)
    if not order: raise HTTPException(404, "Order not found")
    if order.telegram_id != current_user.telegram_id: raise HTTPException(403, "Order belongs to another user")
    if order.status != "WAITING_DETAILS" or order.claimed_by is None:
        raise HTTPException(409, "Order is not waiting for details")
    store_credentials(db, kind, order.id, data.konami_login, data.konami_password)
    order.status = "WAITING_OPERATOR"
    db.add(CoinOrderMessage(order_type=kind, order_id=order.id, telegram_id=order.telegram_id,
        sender="SYSTEM", sender_id=None, message="MyKonami ma’lumotlari xavfsiz qabul qilindi."))
    db.commit(); db.refresh(order)
    return {"success": True, "status": order.status}


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


@router.post("/internal/{order_type}/{order_id}/credential-grant")
def admin_credentials(order_type: str, order_id: int, data: CredentialOpenRequest, request: Request,
    _: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    kind = normalize_order_type(order_type)
    if not kind: raise HTTPException(404, "Order not found")
    order = get_coin_order_for_update(db, kind, order_id)
    if not order: raise HTTPException(404, "Order not found")
    if order.status in TERMINAL_STATUSES: raise HTTPException(410, "Credentials were destroyed")
    require_credential_operator(kind, order, data.admin_id, assign=True)
    token = create_access_grant(db, kind, order_id, data.admin_id)
    return {"success": True, "view_path": f"/coin-order-chat/credential-view/{token}"}


@router.get("/credential-view/{token}", response_class=HTMLResponse)
def credential_view(token: str):
    html = """<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Admin verification</title><script src='https://telegram.org/js/telegram-web-app.js'></script><style>body{font-family:sans-serif;background:#090b10;color:#fff;padding:24px}main{max-width:420px;margin:auto;background:#171a22;padding:20px;border-radius:18px}</style><main><h2>Admin tekshirilmoqda…</h2><p id='status'>Telegram tasdiqlashi kutilmoqda.</p><form method='post'><input id='init' type='hidden' name='init_data'></form></main><script>const data=window.Telegram&&Telegram.WebApp&&Telegram.WebApp.initData;if(data){document.getElementById('init').value=data;document.querySelector('form').submit()}else{document.getElementById('status').textContent='Bu oynani admin bot ichidan oching.'}</script>"""
    return HTMLResponse(html, headers=credential_headers(script=True))


@router.post("/credential-view/{token}", response_class=HTMLResponse)
def credential_view_open(token: str, request: Request, init_data: str = Form(...), db: Session = Depends(get_db)):
    admin = verify_init_data(init_data)
    grant = consume_access_grant(db, token, admin.telegram_id)
    if not grant: raise HTTPException(410, "Credential link expired or used")
    order = get_coin_order(db, grant.order_type, grant.order_id)
    if not order or order.status in TERMINAL_STATUSES: raise HTTPException(410, "Credentials are unavailable")
    require_credential_operator(grant.order_type, order, admin.telegram_id)
    credentials = open_credentials(db, grant.order_type, grant.order_id, grant.admin_id,
        request.client.host if request.client else None, f"grant:{grant.id}")
    if not credentials: raise HTTPException(410, "Credentials are unavailable")
    email = escape(credentials["email"], quote=True); password = escape(credentials["password"], quote=True)
    html = f"""<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Credential</title>
<script src='https://telegram.org/js/telegram-web-app.js'></script><style>body{{font-family:sans-serif;background:#090b10;color:#fff;padding:20px}}main{{max-width:420px;margin:auto;background:#171a22;padding:20px;border-radius:18px}}input,code{{box-sizing:border-box;width:100%;display:block;padding:12px;background:#050609;color:#fff;border:1px solid #303542;border-radius:10px;margin:8px 0;word-break:break-all}}button{{padding:10px 14px;margin:4px 4px 12px 0;border:0;border-radius:10px}}hr{{border-color:#303542}}</style>
<main id='card'><h2>MyKonami credential</h2><small>Order #{grant.order_id}</small><p>📧 MyKonami Email</p><code id='email'>{email}</code><button onclick="copyValue('EMAIL_COPY','email')">📋 Nusxalash</button><hr><p>🔑 MyKonami Password</p><input id='password' type='password' readonly value='{password}'><button onclick='revealPassword()'>👁 Ko‘rsatish</button><button onclick="copyValue('PASSWORD_COPY','password')">📋 Nusxalash</button><p id='status'>Faqat vakolatli operator uchun.</p></main>
<script>async function audit(action){{const init_data=window.Telegram&&Telegram.WebApp&&Telegram.WebApp.initData||'';const body=new URLSearchParams({{init_data,action}});const r=await fetch(location.pathname+'/audit',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body}});if(!r.ok){{document.getElementById('card').innerHTML='<h2>Credential deleted</h2>';return false}}return true}}async function revealPassword(){{if(await audit('PASSWORD_REVEAL'))document.getElementById('password').type='text'}}async function copyValue(action,id){{if(!(await audit(action)))return;const el=document.getElementById(id);await navigator.clipboard.writeText(el.value||el.textContent);document.getElementById('status').textContent='Nusxalandi.'}}</script>"""
    return HTMLResponse(html, headers=credential_headers(script=True))


@router.post("/credential-view/{token}/audit")
def credential_view_audit(token: str, request: Request, init_data: str = Form(...), action: str = Form(...), db: Session = Depends(get_db)):
    admin = verify_init_data(init_data); action = action.upper()
    if action not in AUDIT_ACTIONS: raise HTTPException(400, "Invalid credential action")
    grant = get_consumed_access_grant(db, token, admin.telegram_id)
    if not grant: raise HTTPException(410, "Credential session expired")
    order = get_coin_order(db, grant.order_type, grant.order_id)
    if not order or order.status in TERMINAL_STATUSES: raise HTTPException(410, "Credentials were destroyed")
    require_credential_operator(grant.order_type, order, admin.telegram_id)
    count = record_credential_access_event(db, grant.order_type, grant.order_id, admin.telegram_id, action,
        request.client.host if request.client else None, f"grant:{grant.id}")
    return {"success": True, "action": action, "count": count}


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
