from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.arena_internal_auth import require_arena_internal_api_key
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.crud import match as match_crud
from app.models.match import MatchStatus
from app.services.arena_state_machine import ArenaTransitionError
from app.schemas.match import (
    MatchAccept,
    MatchAdminResolve,
    MatchCancel,
    MatchCreate,
    MatchGuideResponse,
    MatchInternalResponse,
    MatchInternalListResponse,
    MatchListResponse,
    MatchLeaderboardResponse,
    MatchParticipantResponse,
    MatchReady,
    MatchResponse,
    MatchRoomCodeCreate,
    MatchScreenshotUpload,
    MatchStatsResponse,
)


router = APIRouter(prefix="/matches", tags=["1vs1 Arena"])


def _raise_match_error(error: ValueError) -> None:
    message = str(error)
    if isinstance(error, ArenaTransitionError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    if "topilmadi" in message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if (
        "ishtirokchisi emassiz" in message
        or "Faqat match yaratuvchisi" in message
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
    if any(
        marker in message
        for marker in (
            "qabul qilib bo‘lmaydi",
            "allaqachon",
            "vaqti emas",
            "Hozir ready",
            "yakunlangan",
            "O‘zingiz",
        )
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _participant_response(match, telegram_id: int) -> MatchParticipantResponse:
    response = MatchParticipantResponse.model_validate(match)
    room_code_visible = (
        match_crud.is_match_participant(match, telegram_id)
        and match.status
        in {
            MatchStatus.ROOM_READY,
            MatchStatus.PLAYING,
            MatchStatus.WAITING_ADMIN,
        }
    )
    return response.model_copy(
        update={"room_code": match.room_code if room_code_visible else None}
    )


@router.post("/", response_model=MatchParticipantResponse)
def create_match(
    payload: MatchCreate,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    if not payload.rules_accepted:
        raise HTTPException(status_code=400, detail="Match qoidalarini qabul qilish majburiy")
    try:
        match = match_crud.create_match(
            db=db,
            creator_telegram_id=current_user.telegram_id,
            efc_amount=payload.stake_efc,
            scheduled_at=payload.scheduled_at,
            game_type=payload.game_type,
            rules_accepted=payload.rules_accepted,
        )
        return _participant_response(match, current_user.telegram_id)
    except ValueError as error:
        _raise_match_error(error)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Match yaratib bo‘lmadi")


@router.get("/open", response_model=MatchListResponse)
def get_open_matches(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    _: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return {"matches": match_crud.get_open_matches(db=db, skip=skip, limit=limit)}


# These worker routes remain legacy/internal until Sprint 18B-3. Their
# response stays internal so the existing worker can read participant IDs.
@router.get("/worker/due-scheduled", response_model=MatchInternalListResponse)
def get_due_scheduled_matches(
    limit: int = Query(default=50, ge=1, le=100),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return {"matches": match_crud.get_due_scheduled_matches(db=db, limit=limit)}


@router.get("/worker/expired-ready", response_model=MatchInternalListResponse)
def get_expired_ready_matches(
    limit: int = Query(default=50, ge=1, le=100),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return {"matches": match_crud.get_expired_ready_matches(db=db, limit=limit)}


@router.get("/me", response_model=MatchListResponse)
def get_my_matches(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    matches = match_crud.get_user_matches(
        db=db,
        telegram_id=current_user.telegram_id,
        skip=skip,
        limit=limit,
    )
    return {"matches": matches}


@router.get("/guide", response_model=MatchGuideResponse)
def get_match_guide(_: TelegramUser = Depends(get_current_telegram_user)):
    return match_crud.get_match_guide()


@router.get("/leaderboard", response_model=MatchLeaderboardResponse)
def get_leaderboard(
    period: str = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    _: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return {"users": match_crud.get_leaderboard(db=db, period=period, limit=limit)}


@router.get("/stats/me", response_model=MatchStatsResponse)
def get_my_match_stats(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return match_crud.get_match_stats(db=db, telegram_id=current_user.telegram_id)


@router.get("/{match_id}", response_model=MatchParticipantResponse)
def get_match(
    match_id: int,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    match = match_crud.get_match(db=db, match_id=match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match topilmadi")
    return _participant_response(match, current_user.telegram_id)


@router.post("/{match_id}/accept", response_model=MatchParticipantResponse)
def accept_match(
    match_id: int,
    payload: MatchAccept,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    if not payload.rules_accepted:
        raise HTTPException(status_code=400, detail="Match qoidalarini qabul qilish majburiy")
    try:
        match = match_crud.accept_match(
            db=db,
            match_id=match_id,
            opponent_telegram_id=current_user.telegram_id,
            rules_accepted=payload.rules_accepted,
        )
        return _participant_response(match, current_user.telegram_id)
    except ValueError as error:
        _raise_match_error(error)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Matchga qo‘shilib bo‘lmadi")


@router.post("/{match_id}/start-ready-check", response_model=MatchInternalResponse)
def start_ready_check(
    match_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    # Legacy worker route; it is intentionally not a user-facing API.
    try:
        return match_crud.start_ready_check(db=db, match_id=match_id)
    except ValueError as error:
        _raise_match_error(error)


@router.post("/{match_id}/ready", response_model=MatchParticipantResponse)
def set_player_ready(
    match_id: int,
    _: MatchReady,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = match_crud.set_player_ready(
            db=db,
            match_id=match_id,
            telegram_id=current_user.telegram_id,
        )
        return _participant_response(match, current_user.telegram_id)
    except ValueError as error:
        _raise_match_error(error)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Tayyor holatini saqlab bo‘lmadi")


@router.post("/{match_id}/finish-ready-check", response_model=MatchInternalResponse)
def finish_ready_check(
    match_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    # Legacy worker route; it is intentionally not a user-facing API.
    try:
        return match_crud.finish_ready_check(db=db, match_id=match_id)
    except ValueError as error:
        _raise_match_error(error)


@router.post("/{match_id}/room-code", response_model=MatchParticipantResponse)
def create_room_code(
    match_id: int,
    payload: MatchRoomCodeCreate,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = match_crud.create_room_code(
            db=db,
            match_id=match_id,
            telegram_id=current_user.telegram_id,
            room_code=payload.room_code,
        )
        return _participant_response(match, current_user.telegram_id)
    except ValueError as error:
        _raise_match_error(error)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Room code saqlanmadi")


@router.post("/{match_id}/screenshot", response_model=MatchParticipantResponse)
def upload_result_screenshot(
    match_id: int,
    payload: MatchScreenshotUpload,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        match = match_crud.upload_result_screenshot(
            db=db,
            match_id=match_id,
            telegram_id=current_user.telegram_id,
            screenshot_file_id=payload.screenshot_file_id,
            video_file_id=payload.video_file_id,
        )
        return _participant_response(match, current_user.telegram_id)
    except ValueError as error:
        _raise_match_error(error)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Screenshot saqlanmadi")


@router.post("/{match_id}/resolve", response_model=MatchInternalResponse)
def resolve_match(
    match_id: int,
    payload: MatchAdminResolve,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    # Legacy admin/internal route. It is moved behind internal auth in 18B-3.
    try:
        return match_crud.resolve_match(
            db=db,
            match_id=match_id,
            admin_telegram_id=payload.admin_telegram_id,
            winner_telegram_id=payload.winner_telegram_id,
            decision=payload.decision,
            admin_comment=payload.admin_comment,
        )
    except ValueError as error:
        _raise_match_error(error)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Admin qarorini saqlab bo‘lmadi")


@router.post("/{match_id}/cancel", response_model=MatchParticipantResponse)
def cancel_match(
    match_id: int,
    payload: MatchCancel,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    match = match_crud.get_match(db=db, match_id=match_id)
    if not match:
        raise HTTPException(status_code=404, detail="Match topilmadi")
    if not match_crud.is_match_participant(match, current_user.telegram_id):
        raise HTTPException(status_code=403, detail="Siz bu match ishtirokchisi emassiz")
    try:
        match = match_crud.cancel_match(
            db=db,
            match_id=match_id,
            cancel_reason=payload.cancel_reason,
        )
        return _participant_response(match, current_user.telegram_id)
    except ValueError as error:
        _raise_match_error(error)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Matchni bekor qilib bo‘lmadi")
