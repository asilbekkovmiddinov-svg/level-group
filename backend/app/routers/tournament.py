from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.tournament import TournamentParticipantStatus
from app.schemas.tournament import (
    TournamentApplicationDecision,
    TournamentCreate,
    TournamentMatchReschedule,
    TournamentMatchResponse,
    TournamentMatchSchedule,
    TournamentOverviewResponse,
    TournamentParticipantResponse,
    TournamentResponse,
)
from app.services.tournament import TournamentService, TournamentServiceError


router = APIRouter(prefix="/tournaments", tags=["Tournaments"])
admin_router = APIRouter(prefix="/admin/tournaments", tags=["Tournament Admin"])


def tournament_call(callback):
    try:
        return callback()
    except TournamentServiceError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/current", response_model=TournamentOverviewResponse)
def current(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    service = TournamentService(db)
    tournament = service.current()
    if tournament is None:
        return {
            "tournament": None,
            "participant": None,
            "participants": [],
            "matches": [],
        }
    return {
        "tournament": tournament,
        "participant": service.participant(tournament.id, current_user.telegram_id),
        "participants": service.public_participants(tournament.id),
        "matches": service.matches(tournament.id),
    }


@router.post(
    "/{tournament_id}/apply",
    response_model=TournamentParticipantResponse,
    status_code=201,
)
def apply(
    tournament_id: int,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).apply(
            tournament_id, current_user.telegram_id
        )
    )


@router.get(
    "/{tournament_id}/matches",
    response_model=list[TournamentMatchResponse],
)
def matches(
    tournament_id: int,
    _current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return tournament_call(lambda: TournamentService(db).matches(tournament_id))


@admin_router.post("", response_model=TournamentResponse, status_code=201)
def create(
    payload: TournamentCreate,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).create(payload, admin.telegram_id)
    )


@admin_router.get(
    "/{tournament_id}/applications",
    response_model=list[TournamentParticipantResponse],
)
def applications(
    tournament_id: int,
    status: TournamentParticipantStatus | None = Query(default=None),
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).applications(tournament_id, status)
    )


@admin_router.post(
    "/{tournament_id}/applications/{participant_id}/decision",
    response_model=TournamentParticipantResponse,
)
def decide(
    tournament_id: int,
    participant_id: int,
    payload: TournamentApplicationDecision,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).review(
            tournament_id,
            participant_id,
            payload,
            admin.telegram_id,
        )
    )


@admin_router.post(
    "/{tournament_id}/matches",
    response_model=TournamentMatchResponse,
    status_code=201,
)
def schedule_match(
    tournament_id: int,
    payload: TournamentMatchSchedule,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).schedule_match(
            tournament_id, payload, admin.telegram_id
        )
    )


@admin_router.patch(
    "/{tournament_id}/matches/{match_id}/schedule",
    response_model=TournamentMatchResponse,
)
def reschedule_match(
    tournament_id: int,
    match_id: str,
    payload: TournamentMatchReschedule,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).reschedule(
            tournament_id, match_id, payload.scheduled_at
        )
    )


@admin_router.post(
    "/{tournament_id}/start",
    response_model=TournamentResponse,
)
def start(
    tournament_id: int,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(lambda: TournamentService(db).start(tournament_id))


@admin_router.post(
    "/{tournament_id}/matches/{match_id}/open",
    response_model=TournamentMatchResponse,
)
def open_match(
    tournament_id: int,
    match_id: str,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).open_match(tournament_id, match_id)
    )
