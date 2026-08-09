from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.wall_rush import JoinMatchRequest, WallRushActionRequest
from app.services.wall_rush import (
    WallRushError, get_active_match, get_wallet, join_match, match_response,
    process_timeout, submit_action, wallet_response,
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
