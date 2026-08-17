import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user, verify_init_data
from app.schemas.penalty_duel import PenaltyDuelChoiceRequest, PenaltyDuelJoinRequest
from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelMode, PenaltyDuelStatus
from app.services.penalty_duel import PenaltyDuelError, cancel_waiting_match, get_active_match, join_match, match_response
from app.services.penalty_duel_ai import activate_ai_opponent, waiting_for_ai
from app.services.penalty_duel_leaderboard import leaderboard_rows
from app.services.penalty_duel_single_choice import player_role, process_single_choice_timeout, submit_single_choice

router = APIRouter(prefix="/penalty-duel", tags=["Penalty Duel"])
PENALTY_WEBSOCKET_REFRESH_SECONDS = 0.25


def _conflict(error: PenaltyDuelError):
    message = str(error)
    status = 404 if "not found" in message.lower() else 409
    raise HTTPException(status_code=status, detail=message)


def _activate_ai_if_due(db: Session, match: PenaltyDuelMatch | None) -> PenaltyDuelMatch | None:
    if match is None or not waiting_for_ai(match): return match
    locked = db.query(PenaltyDuelMatch).filter_by(id=match.id).with_for_update().first()
    if locked is None or locked.status != PenaltyDuelStatus.WAITING:
        db.rollback(); return locked
    try:
        if activate_ai_opponent(db, locked): db.commit(); db.refresh(locked)
        else: db.rollback()
        return locked
    except Exception:
        db.rollback(); raise


def _response(db: Session, match: PenaltyDuelMatch, telegram_id: int) -> dict:
    payload = match_response(db, match, telegram_id)
    if match.status.value == "ACTIVE":
        payload["your_role"] = player_role(match, telegram_id)
        payload["shot_number"] = match.round_number
        payload["regulation_shots"] = 10
        payload["sudden_death"] = match.round_number > 10
    else: payload["your_role"] = None
    return payload


@router.get("/leaderboard")
def leaderboard(mode: PenaltyDuelMode, limit: int = Query(default=20, ge=1, le=50), _: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    return {"mode": mode.value, "rows": leaderboard_rows(db, mode, limit)}


@router.post("/matchmaking/join")
def matchmaking_join(payload: PenaltyDuelJoinRequest, user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    try:
        match = join_match(db, user.telegram_id, payload.mode); match = _activate_ai_if_due(db, match)
        return _response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
        db.rollback(); _conflict(error)


@router.get("/matches/active")
def current_match(user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    match = get_active_match(db, user.telegram_id); match = _activate_ai_if_due(db, match)
    return _response(db, match, user.telegram_id) if match else None


@router.post("/matches/{match_id}/choices")
def round_choices(match_id: str, payload: PenaltyDuelChoiceRequest, user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    try:
        match = submit_single_choice(db, match_id, user.telegram_id, payload.direction.value, payload.idempotency_key)
        return _response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
        db.rollback(); _conflict(error)


@router.post("/matches/{match_id}/cancel-waiting")
def cancel_waiting(match_id: str, user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    try:
        match = cancel_waiting_match(db, match_id, user.telegram_id)
        return _response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
        db.rollback(); _conflict(error)


@router.post("/matches/{match_id}/timeout")
def timeout_round(match_id: str, user: TelegramUser = Depends(get_current_telegram_user), db: Session = Depends(get_db)):
    try:
        match = process_single_choice_timeout(db, match_id, user.telegram_id)
        return _response(db, match, user.telegram_id)
    except PenaltyDuelError as error:
        db.rollback(); _conflict(error)


@router.websocket("/ws")
async def realtime_state(websocket: WebSocket):
    init_data = websocket.query_params.get("init_data")
    if not init_data:
        await websocket.close(code=4401, reason="Telegram authentication required"); return
    try: user = verify_init_data(init_data)
    except HTTPException:
        await websocket.close(code=4401, reason="Invalid Telegram authentication"); return
    await websocket.accept(); db = SessionLocal(); last_signature = object(); tracked_match_id = None
    try:
        while True:
            db.expire_all(); match = get_active_match(db, user.telegram_id); match = _activate_ai_if_due(db, match)
            if match: tracked_match_id = match.id
            elif tracked_match_id: match = db.query(PenaltyDuelMatch).filter_by(id=tracked_match_id).first()
            payload = _response(db, match, user.telegram_id) if match else None
            signature = (payload["id"], payload["version"], payload["status"]) if payload else None
            if signature != last_signature:
                await websocket.send_json({"type": "PENALTY_MATCH_STATE", "match": payload}); last_signature = signature
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=PENALTY_WEBSOCKET_REFRESH_SECONDS)
                if message == "PING": await websocket.send_json({"type": "PONG"})
            except asyncio.TimeoutError: continue
    except WebSocketDisconnect: pass
    finally: db.close()
