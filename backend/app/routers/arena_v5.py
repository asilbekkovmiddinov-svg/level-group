from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.arena_internal_auth import require_arena_internal_api_key
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.arena_v5 import (
    ArenaV5ActiveMatchInternalResponse,
    ArenaV5ConfigResponse,
    ArenaV5HistoryItem,
    ArenaV5ProfileResponse,
    ArenaV5ProfileUpdate,
    ArenaV5QueueResponse,
    ArenaV5RankingResponse,
    ArenaV5RelayValidateRequest,
    ArenaV5StateResponse,
    ArenaV5SubmissionCompleteRequest,
    ArenaV5SubmissionFailedRequest,
    ArenaV5SubmissionPrepareRequest,
    ArenaV5SubmissionResponse,
)
from app.services.arena_v3 import ArenaV3ServiceError
from app.services.arena_v5 import ArenaV5Service
from app.services.arena_v5_history import get_arena_v5_history


router = APIRouter(prefix="/arena/v5", tags=["Arena V5"])
internal_router = APIRouter(
    prefix="/internal/arena/v5", tags=["Arena V5 Internal"]
)


def _call(callback):
    try:
        return callback()
    except ArenaV3ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


def _idempotency_key(
    value: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    normalized = (value or "").strip()
    if not normalized or len(normalized) > 128:
        raise HTTPException(400, "Valid Idempotency-Key is required")
    return normalized


@router.get("/config", response_model=ArenaV5ConfigResponse)
def arena_config(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return _call(
        lambda: ArenaV5Service(db).config_response(current_user.telegram_id)
    )


@router.get("/state", response_model=ArenaV5StateResponse)
def arena_state(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).state(current_user.telegram_id))


@router.post("/queue", response_model=ArenaV5QueueResponse)
def join_queue(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    idempotency_key: str = Depends(_idempotency_key),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).join_queue(
        current_user.telegram_id, idempotency_key
    ))


@router.delete("/queue", response_model=ArenaV5QueueResponse)
def cancel_queue(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).cancel_queue(
        current_user.telegram_id
    ))


@router.get("/profile", response_model=ArenaV5ProfileResponse)
def get_profile(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).profile(
        current_user.telegram_id
    ))


@router.put("/profile", response_model=ArenaV5ProfileResponse)
def update_profile(
    payload: ArenaV5ProfileUpdate,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).update_profile(
        current_user.telegram_id, payload.efootball_username
    ))


@router.get("/ranking", response_model=ArenaV5RankingResponse)
def ranking(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).ranking(
        limit=limit, offset=offset
    ))


@router.get("/history", response_model=list[ArenaV5HistoryItem])
def history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return _call(lambda: get_arena_v5_history(
        db, current_user.telegram_id, limit=limit, offset=offset
    ))


@internal_router.get(
    "/users/{telegram_id}/active-match",
    response_model=ArenaV5ActiveMatchInternalResponse,
)
def active_match_internal(
    telegram_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).active_internal(telegram_id))


@internal_router.post(
    "/relay/validate", response_model=ArenaV5ActiveMatchInternalResponse
)
def validate_relay(
    payload: ArenaV5RelayValidateRequest,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).validate_relay(
        payload.telegram_id, payload.token
    ))


@internal_router.post(
    "/submissions/prepare", response_model=ArenaV5SubmissionResponse
)
def prepare_submission(
    payload: ArenaV5SubmissionPrepareRequest,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).prepare_submission(
        player_id=payload.telegram_id,
        telegram_file_id=payload.telegram_file_id,
        telegram_message_id=payload.telegram_message_id,
    ))


@internal_router.post(
    "/submissions/{submission_id}/complete",
    response_model=ArenaV5SubmissionResponse,
)
def complete_submission(
    submission_id: int,
    payload: ArenaV5SubmissionCompleteRequest,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).complete_submission(
        submission_id, payload.admin_channel_message_id
    ))


@internal_router.post(
    "/submissions/{submission_id}/failed",
    response_model=ArenaV5SubmissionResponse,
)
def fail_submission(
    submission_id: int,
    payload: ArenaV5SubmissionFailedRequest,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return _call(lambda: ArenaV5Service(db).fail_submission(
        submission_id, payload.error
    ))
