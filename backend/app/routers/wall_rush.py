import asyncio
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core import config
from app.core.database import SessionLocal, get_db
from app.core.telegram_auth import (
    TelegramUser, get_current_telegram_user, verify_init_data,
)
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.wall_rush import (
    JoinMatchRequest, TadsWebhookPayload, TrustedAdRewardRequest,
    WallRushActionRequest,
)
from app.models.wall_rush import WallRushMode
from app.services.wall_rush import (
    WallRushError, cancel_waiting_match, get_active_match, get_wallet, grant_ad_ticket, join_match,
    leaderboard_rows, match_response, process_timeout, submit_action, wallet_response,
)

router = APIRouter(prefix="/wall-rush", tags=["Wall Rush"])


def _conflict(error: WallRushError):
    message = str(error)
    status = 404 if "not found" in message.lower() else 409
    raise HTTPException(status_code=status, detail=message)


@router.get("/wallet")
def ticket_wallet(
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    wallet = get_wallet(db, user.telegram_id)
    db.commit()
    return wallet_response(wallet)


@router.post("/rewards/ad")
def trusted_ad_reward(
    payload: TrustedAdRewardRequest,
    _: None = Depends(require_internal_api_key),
    db: Session = Depends(get_db),
):
    try:
        wallet = grant_ad_ticket(
            db,
            payload.telegram_id,
            f"{payload.provider.lower()}:{payload.provider_event_id}",
        )
        return wallet_response(wallet)
    except WallRushError as error:
        db.rollback()
        _conflict(error)


@router.post("/rewards/tads/webhook")
def tads_reward_webhook(
    payload: TadsWebhookPayload,
    secret: str = "",
    db: Session = Depends(get_db),
):
    if not config.TADS_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="TADS webhook is not configured")
    if not hmac.compare_digest(secret, config.TADS_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid TADS webhook secret")
    if not hmac.compare_digest(payload.widget_id, config.TADS_WALL_RUSH_WIDGET_ID):
        raise HTTPException(status_code=403, detail="Unknown TADS widget")
    try:
        telegram_id = int(payload.telegram_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid telegram_id") from error
    if telegram_id <= 0:
        raise HTTPException(status_code=422, detail="Invalid telegram_id")

    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    event_key = f"widget:{payload.widget_id}:user:{telegram_id}:hour:{hour}"
    try:
        wallet = grant_ad_ticket(db, telegram_id, f"tads:{event_key}")
        return {"status": "ok", "rewarded": True, "wallet": wallet_response(wallet)}
    except WallRushError as error:
        db.rollback()
        if "once per hour" in str(error):
            return {"status": "ok", "rewarded": False, "reason": "cooldown"}
        _conflict(error)



@router.get("/leaderboard")
def leaderboard(
    mode: WallRushMode,
    limit: int = Query(default=20, ge=1, le=50),
    _: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return {"mode": mode.value, "rows": leaderboard_rows(db, mode, limit)}



@router.post("/matchmaking/join")
def matchmaking_join(
    payload: JoinMatchRequest,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        return match_response(join_match(db, user.telegram_id, payload.mode))
    except WallRushError as error:
        db.rollback()
        _conflict(error)


@router.post("/matches/{match_id}/cancel-waiting")
def cancel_waiting(
    match_id: str,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        return match_response(cancel_waiting_match(db, match_id, user.telegram_id))
    except WallRushError as error:
        db.rollback()
        _conflict(error)


@router.get("/matches/active")
def active_match(
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    match = get_active_match(db, user.telegram_id)
    return match_response(match) if match else None


@router.get("/matches/{match_id}")
def match_state(
    match_id: str,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    match = get_active_match(db, user.telegram_id)
    if match is None or match.id != match_id:
        raise HTTPException(status_code=404, detail="Match not found")
    return match_response(match)


@router.post("/matches/{match_id}/actions")
def play_action(
    match_id: str,
    payload: WallRushActionRequest,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = submit_action(
            db, match_id, user.telegram_id, payload.action.value,
            payload.row, payload.column, payload.orientation,
            payload.expected_version, payload.idempotency_key,
        )
        return match_response(match)
    except WallRushError as error:
        db.rollback()
        _conflict(error)


@router.post("/matches/{match_id}/timeout")
def timeout_turn(
    match_id: str,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        return match_response(process_timeout(db, match_id, user.telegram_id))
    except WallRushError as error:
        db.rollback()
        _conflict(error)


@router.websocket("/ws")
async def realtime_state(websocket: WebSocket):
    init_data = websocket.query_params.get("init_data")
    if not init_data:
        await websocket.close(code=4401, reason="Telegram authentication required")
        return
    try:
        user = verify_init_data(init_data)
    except HTTPException:
        await websocket.close(code=4401, reason="Invalid Telegram authentication")
        return

    await websocket.accept()
    db = SessionLocal()
    last_signature = object()
    try:
        while True:
            db.expire_all()
            match = get_active_match(db, user.telegram_id)
            payload = match_response(match) if match else None
            signature = (
                payload["id"], payload["version"], payload["status"]
            ) if payload else None
            if signature != last_signature:
                await websocket.send_json({"type": "MATCH_STATE", "match": payload})
                last_signature = signature
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(), timeout=1.0
                )
                if message == "PING":
                    await websocket.send_json({"type": "PONG"})
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        db.close()
