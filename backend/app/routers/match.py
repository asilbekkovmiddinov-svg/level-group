from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud import match as match_crud
from app.schemas.match import (
    MatchAccept,
    MatchAdminResolve,
    MatchCancel,
    MatchCreate,
    MatchGuideResponse,
    MatchLeaderboardResponse,
    MatchListResponse,
    MatchReady,
    MatchResponse,
    MatchRoomCodeCreate,
    MatchScreenshotUpload,
    MatchStatsResponse,
)

router = APIRouter(prefix="/matches", tags=["1vs1 Arena"])


@router.post("/", response_model=MatchResponse)
def create_match(payload: MatchCreate, db: Session = Depends(get_db)):
    try:
        return match_crud.create_match(
            db=db,
            creator_telegram_id=payload.creator_telegram_id,
            efc_amount=payload.efc_amount,
            scheduled_at=payload.scheduled_at,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/open", response_model=MatchListResponse)
def get_open_matches(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    matches = match_crud.get_open_matches(db=db, skip=skip, limit=limit)
    return {"matches": matches}


@router.get("/worker/due-scheduled", response_model=MatchListResponse)
def get_due_scheduled_matches(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    matches = match_crud.get_due_scheduled_matches(db=db, limit=limit)
    return {"matches": matches}


@router.get("/worker/expired-ready", response_model=MatchListResponse)
def get_expired_ready_matches(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    matches = match_crud.get_expired_ready_matches(db=db, limit=limit)
    return {"matches": matches}


@router.get("/user/{telegram_id}", response_model=MatchListResponse)
def get_user_matches(
    telegram_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    matches = match_crud.get_user_matches(
        db=db,
        telegram_id=telegram_id,
        skip=skip,
        limit=limit,
    )
    return {"matches": matches}


@router.get("/guide", response_model=MatchGuideResponse)
def get_match_guide():
    return match_crud.get_match_guide()


@router.get("/leaderboard", response_model=MatchLeaderboardResponse)
def get_leaderboard(
    period: str = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    users = match_crud.get_leaderboard(db=db, period=period, limit=limit)
    return {"users": users}


@router.get("/stats/{telegram_id}", response_model=MatchStatsResponse)
def get_match_stats(telegram_id: int, db: Session = Depends(get_db)):
    return match_crud.get_match_stats(db=db, telegram_id=telegram_id)


@router.get("/{match_id}", response_model=MatchResponse)
def get_match(match_id: int, db: Session = Depends(get_db)):
    match = match_crud.get_match(db=db, match_id=match_id)

    if not match:
        raise HTTPException(status_code=404, detail="Match topilmadi")

    return match


@router.post("/{match_id}/accept", response_model=MatchResponse)
def accept_match(
    match_id: int,
    payload: MatchAccept,
    db: Session = Depends(get_db),
):
    try:
        return match_crud.accept_match(
            db=db,
            match_id=match_id,
            opponent_telegram_id=payload.opponent_telegram_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/{match_id}/start-ready-check", response_model=MatchResponse)
def start_ready_check(match_id: int, db: Session = Depends(get_db)):
    try:
        return match_crud.start_ready_check(db=db, match_id=match_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/{match_id}/ready", response_model=MatchResponse)
def set_player_ready(
    match_id: int,
    payload: MatchReady,
    db: Session = Depends(get_db),
):
    try:
        return match_crud.set_player_ready(
            db=db,
            match_id=match_id,
            telegram_id=payload.telegram_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/{match_id}/finish-ready-check", response_model=MatchResponse)
def finish_ready_check(match_id: int, db: Session = Depends(get_db)):
    try:
        return match_crud.finish_ready_check(db=db, match_id=match_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/{match_id}/room-code", response_model=MatchResponse)
def create_room_code(
    match_id: int,
    payload: MatchRoomCodeCreate,
    db: Session = Depends(get_db),
):
    try:
        return match_crud.create_room_code(
            db=db,
            match_id=match_id,
            telegram_id=payload.telegram_id,
            room_code=payload.room_code,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/{match_id}/screenshot", response_model=MatchResponse)
def upload_result_screenshot(
    match_id: int,
    payload: MatchScreenshotUpload,
    db: Session = Depends(get_db),
):
    try:
        return match_crud.upload_result_screenshot(
            db=db,
            match_id=match_id,
            telegram_id=payload.telegram_id,
            screenshot_file_id=payload.screenshot_file_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/{match_id}/resolve", response_model=MatchResponse)
def resolve_match(
    match_id: int,
    payload: MatchAdminResolve,
    db: Session = Depends(get_db),
):
    try:
        return match_crud.resolve_match(
            db=db,
            match_id=match_id,
            admin_telegram_id=payload.admin_telegram_id,
            winner_telegram_id=payload.winner_telegram_id,
            admin_comment=payload.admin_comment,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/{match_id}/cancel", response_model=MatchResponse)
def cancel_match(
    match_id: int,
    payload: MatchCancel,
    db: Session = Depends(get_db),
):
    try:
        return match_crud.cancel_match(
            db=db,
            match_id=match_id,
            cancel_reason=payload.cancel_reason,
            admin_telegram_id=payload.admin_telegram_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
