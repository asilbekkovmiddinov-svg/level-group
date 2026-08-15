from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.tournament import TournamentMatchStatus, TournamentParticipantStatus
from app.schemas.tournament import (
    TournamentApplicationDecision,
    TournamentCreate,
    TournamentGroupFinalizeResponse,
    TournamentMatchReschedule,
    TournamentManualResult,
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
            "tournament_tickets": service.ticket_balance(
                current_user.telegram_id
            ),
            "participant_count": 0,
            "match_count": 0,
            "current_round": 0,
            "total_rounds": 0,
            "is_truncated": False,
            "participants": [],
            "matches": [],
        }
    participant_count = service.participant_count(tournament.id)
    match_count = service.match_count(tournament.id)
    current_round = service.current_round(tournament.id)
    visible_matches = service.matches(
        tournament.id,
        limit=100,
    )
    my_matches = service.matches(
        tournament.id,
        player_id=current_user.telegram_id,
        limit=20,
    )
    matches_by_id = {match.id: match for match in visible_matches}
    matches_by_id.update({match.id: match for match in my_matches})
    visible_matches = list(matches_by_id.values())
    participants = service.public_participants(tournament.id, limit=100)
    visible_player_ids = {
        player_id
        for match in visible_matches
        for player_id in (match.player_a_id, match.player_b_id)
    }
    participants_by_id = {row.telegram_id: row for row in participants}
    participants_by_id.update({
        row.telegram_id: row
        for row in service.participants_by_telegram_ids(
            tournament.id, visible_player_ids
        )
    })
    return {
        "tournament": tournament,
        "participant": service.participant(tournament.id, current_user.telegram_id),
        "tournament_tickets": service.ticket_balance(current_user.telegram_id),
        "participant_count": participant_count,
        "match_count": match_count,
        "current_round": current_round,
        "total_rounds": (
            service.total_rounds(participant_count) if participant_count >= 2 else 0
        ),
        "is_truncated": (
            participant_count > len(participants_by_id)
            or match_count > len(visible_matches)
        ),
        "participants": list(participants_by_id.values()),
        "matches": visible_matches,
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
    round_number: int | None = Query(default=None, ge=1),
    status: TournamentMatchStatus | None = Query(default=None),
    mine: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    return tournament_call(lambda: TournamentService(db).matches(
        tournament_id,
        round_number=round_number,
        status=status,
        player_id=current_user.telegram_id if mine else None,
        limit=limit,
        offset=offset,
    ))


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
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=64),
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).applications(
            tournament_id,
            status,
            limit=limit,
            offset=offset,
            search=search,
        )
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


@admin_router.put(
    "/{tournament_id}/matches/{match_id}/result",
    response_model=TournamentMatchResponse,
)
def record_result(
    tournament_id: int,
    match_id: str,
    payload: TournamentManualResult,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).record_result(
            tournament_id, match_id, payload, admin.telegram_id
        )
    )


@admin_router.post(
    "/{tournament_id}/groups/finalize",
    response_model=TournamentGroupFinalizeResponse,
)
def finalize_groups(
    tournament_id: int,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).finalize_groups(tournament_id)
    )


@admin_router.post(
    "/{tournament_id}/start",
    response_model=TournamentResponse,
)
def start(
    tournament_id: int,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return tournament_call(
        lambda: TournamentService(db).start(tournament_id, admin.telegram_id)
    )
