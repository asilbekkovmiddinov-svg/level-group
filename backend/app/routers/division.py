from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.division import DivisionParticipantStatus
from app.schemas.division import (
    DivisionApplicationDecision,
    DivisionApplicationListResponse,
    DivisionMatchResponse,
    DivisionOverviewResponse,
    DivisionParticipantResponse,
    DivisionSeasonCreate,
    DivisionSeasonResponse,
    DivisionStandingsResponse,
)
from app.services.division import DivisionService, DivisionServiceError


router = APIRouter(prefix="/division", tags=["Global Division"])
admin_router = APIRouter(prefix="/admin/division", tags=["Global Division Admin"])


def division_call(callback):
    try:
        return callback()
    except DivisionServiceError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("", response_model=DivisionOverviewResponse)
def overview(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return DivisionService(db).overview(current_user.telegram_id)


@router.post(
    "/apply", response_model=DivisionParticipantResponse, status_code=201
)
def apply(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return division_call(
        lambda: DivisionService(db).apply(current_user.telegram_id)
    )


@router.get("/me", response_model=DivisionOverviewResponse)
def my_division(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return DivisionService(db).overview(current_user.telegram_id)


@router.get("/standings", response_model=DivisionStandingsResponse)
def standings(
    season_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    season, items, total = division_call(
        lambda: DivisionService(db).standings(season_id, limit, offset)
    )
    return {
        "season": season,
        "items": items,
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@router.post(
    "/matchmaking/join", response_model=DivisionMatchResponse
)
def join_matchmaking(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return division_call(
        lambda: DivisionService(db).join_matchmaking(
            current_user.telegram_id
        )
    )


@router.get(
    "/matches/active", response_model=DivisionMatchResponse | None
)
def active_division_match(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    season = DivisionService(db).current_season()
    if season is None:
        return None
    return DivisionService(db).active_match(
        season.id, current_user.telegram_id
    )


@router.post(
    "/matches/{match_id}/cancel-waiting",
    response_model=DivisionMatchResponse,
)
def cancel_waiting_match(
    match_id: str,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return division_call(
        lambda: DivisionService(db).cancel_waiting_match(
            match_id, current_user.telegram_id
        )
    )


@admin_router.post(
    "/seasons", response_model=DivisionSeasonResponse, status_code=201
)
def create_season(
    payload: DivisionSeasonCreate,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return division_call(
        lambda: DivisionService(db).create_season(payload, admin.telegram_id)
    )


@admin_router.post(
    "/seasons/{season_id}/start", response_model=DivisionSeasonResponse
)
def start_season(
    season_id: int,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return division_call(lambda: DivisionService(db).start_season(season_id))


@admin_router.post(
    "/seasons/{season_id}/finish", response_model=DivisionSeasonResponse
)
def finish_season(
    season_id: int,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return division_call(lambda: DivisionService(db).finish_season(season_id))


@admin_router.get(
    "/seasons/{season_id}/applications",
    response_model=DivisionApplicationListResponse,
)
def applications(
    season_id: int,
    application_status: DivisionParticipantStatus | None = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    season, items, total = division_call(
        lambda: DivisionService(db).list_applications(
            season_id, application_status, limit, offset
        )
    )
    return {
        "season": season,
        "items": items,
        "limit": limit,
        "offset": offset,
        "total": total,
    }


@admin_router.post(
    "/seasons/{season_id}/applications/{participant_id}/decision",
    response_model=DivisionParticipantResponse,
)
def decide_application(
    season_id: int,
    participant_id: int,
    payload: DivisionApplicationDecision,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return division_call(
        lambda: DivisionService(db).review_application(
            season_id=season_id,
            participant_id=participant_id,
            decision=DivisionParticipantStatus(payload.decision),
            admin_id=admin.telegram_id,
        )
    )
