import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user, verify_init_data
from app.schemas.penalty_duel import PenaltyDuelChoiceRequest, PenaltyDuelJoinRequest
from app.models.penalty_duel import PenaltyDuelMatch
from app.services.penalty_duel import (
    PenaltyDuelError,
    cancel_waiting_match,
    get_active_match,
    join_match,
    match_response,
    process_timeout,
    submit_choices,
)

router = APIRouter(prefix="/penalty-duel", tags=["Penalty Duel"])
PENALTY_WEBSOCKET_REFRESH_SECONDS = 0.25


def _conflict(error: PenaltyDuelError):
    message = str(error)
    status = 404 if "not found" in message.lower() else 409
    raise HTTPException(status_code=status, detail=message)


@router.post("/matchmaking/join")
def matchmaking_join(
    payload: PenaltyDuelJoinRequest,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = join_match(db, user.telegram_id, payload.mode)
        return match_response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
        db.rollback()
        _conflict(error)


@router.get("/matches/active")
def current_match(
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    match = get_active_match(db, user.telegram_id)
    return match_response(db, match, user.telegram_id) if match else None


@router.post("/matches/{match_id}/choices")
def round_choices(
    match_id: str,
    payload: PenaltyDuelChoiceRequest,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = submit_choices(
            db,
            match_id,
            user.telegram_id,
            payload.kick_direction.value,
            payload.keeper_direction.value,
            payload.expected_version,
            payload.idempotency_key,
        )
        return match_response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
        db.rollback()
        _conflict(error)


@router.post("/matches/{match_id}/cancel-waiting")
def cancel_waiting(
    match_id: str,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = cancel_waiting_match(db, match_id, user.telegram_id)
        return match_response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
        db.rollback()
        _conflict(error)


@router.post("/matches/{match_id}/timeout")
def timeout_round(
    match_id: str,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = process_timeout(db, match_id, user.telegram_id)
        return match_response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
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
    tracked_match_id = None
    try:
        while True:
            db.expire_all()
            match = get_active_match(db, user.telegram_id)
            if match:
                tracked_match_id = match.id
            elif tracked_match_id:
                match = db.query(PenaltyDuelMatch).filter_by(id=tracked_match_id).first()
            payload = match_response(db, match, user.telegram_id) if match else None
            signature = (
                payload["id"], payload["version"], payload["status"]
            ) if payload else None
            if signature != last_signature:
                await websocket.send_json({"type": "PENALTY_MATCH_STATE", "match": payload})
                last_signature = signature
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=PENALTY_WEBSOCKET_REFRESH_SECONDS,
                )
                if message == "PING":
                    await websocket.send_json({"type": "PONG"})
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        db.close()
