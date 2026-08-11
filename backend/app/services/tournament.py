from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.tournament import (
    Tournament,
    TournamentFormat,
    TournamentMatch,
    TournamentMatchStatus,
    TournamentParticipant,
    TournamentParticipantStatus,
    TournamentStatus,
)
from app.schemas.tournament import (
    TournamentApplicationDecision,
    TournamentCreate,
    TournamentMatchSchedule,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class TournamentServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class TournamentService:
    def __init__(self, db: Session):
        self.db = db

    def current(self) -> Tournament | None:
        return (
            self.db.query(Tournament)
            .filter(
                Tournament.status.in_(
                    [
                        TournamentStatus.REGISTRATION,
                        TournamentStatus.ACTIVE,
                    ]
                )
            )
            .order_by(Tournament.id.desc())
            .first()
        )

    def require(self, tournament_id: int) -> Tournament:
        tournament = self.db.get(Tournament, tournament_id)
        if tournament is None:
            raise TournamentServiceError(404, "Tournament not found")
        return tournament

    def create(self, payload: TournamentCreate, admin_id: int) -> Tournament:
        registration_opens_at = as_utc(payload.registration_opens_at)
        registration_closes_at = as_utc(payload.registration_closes_at)
        starts_at = as_utc(payload.starts_at)
        ends_at = as_utc(payload.ends_at)
        if not registration_opens_at < registration_closes_at <= starts_at < ends_at:
            raise TournamentServiceError(422, "Tournament dates are invalid")
        if (
            payload.format == TournamentFormat.GROUP_PLAYOFF
            and payload.group_count * payload.qualifiers_per_group
            > payload.max_participants
        ):
            raise TournamentServiceError(
                422, "Group qualifiers cannot exceed participant capacity"
            )
        tournament = Tournament(
            name=payload.name.strip(),
            format=payload.format,
            status=TournamentStatus.REGISTRATION,
            max_participants=payload.max_participants,
            ticket_cost=payload.ticket_cost,
            group_count=payload.group_count,
            qualifiers_per_group=payload.qualifiers_per_group,
            registration_opens_at=registration_opens_at,
            registration_closes_at=registration_closes_at,
            starts_at=starts_at,
            ends_at=ends_at,
            created_by=admin_id,
        )
        self.db.add(tournament)
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def participant(
        self, tournament_id: int, telegram_id: int
    ) -> TournamentParticipant | None:
        return (
            self.db.query(TournamentParticipant)
            .filter_by(tournament_id=tournament_id, telegram_id=telegram_id)
            .one_or_none()
        )

    def apply(self, tournament_id: int, telegram_id: int) -> TournamentParticipant:
        tournament = self.require(tournament_id)
        now = utc_now()
        if tournament.status != TournamentStatus.REGISTRATION:
            raise TournamentServiceError(409, "Tournament registration is closed")
        if not (
            as_utc(tournament.registration_opens_at)
            <= now
            <= as_utc(tournament.registration_closes_at)
        ):
            raise TournamentServiceError(409, "Tournament registration window is closed")
        existing = self.participant(tournament_id, telegram_id)
        if existing is not None:
            return existing
        participant = TournamentParticipant(
            tournament_id=tournament_id,
            telegram_id=telegram_id,
            status=TournamentParticipantStatus.PENDING,
        )
        self.db.add(participant)
        self.db.commit()
        self.db.refresh(participant)
        return participant

    def applications(
        self,
        tournament_id: int,
        status: TournamentParticipantStatus | None,
    ) -> list[TournamentParticipant]:
        self.require(tournament_id)
        query = self.db.query(TournamentParticipant).filter_by(
            tournament_id=tournament_id
        )
        if status is not None:
            query = query.filter(TournamentParticipant.status == status)
        return query.order_by(TournamentParticipant.applied_at).all()

    def review(
        self,
        tournament_id: int,
        participant_id: int,
        payload: TournamentApplicationDecision,
        admin_id: int,
    ) -> TournamentParticipant:
        tournament = self.require(tournament_id)
        participant = (
            self.db.query(TournamentParticipant)
            .filter_by(id=participant_id, tournament_id=tournament_id)
            .one_or_none()
        )
        if participant is None:
            raise TournamentServiceError(404, "Tournament application not found")
        if participant.status != TournamentParticipantStatus.PENDING:
            raise TournamentServiceError(409, "Application is already reviewed")
        decision = TournamentParticipantStatus(payload.decision)
        if decision == TournamentParticipantStatus.APPROVED:
            approved = (
                self.db.query(TournamentParticipant)
                .filter_by(
                    tournament_id=tournament_id,
                    status=TournamentParticipantStatus.APPROVED,
                )
                .count()
            )
            if approved >= tournament.max_participants:
                raise TournamentServiceError(409, "Tournament capacity is full")
            if tournament.format == TournamentFormat.SINGLE_ELIMINATION:
                if payload.group_name is not None:
                    raise TournamentServiceError(422, "Olympic format has no groups")
            elif not payload.group_name:
                raise TournamentServiceError(422, "Group assignment is required")
            participant.seed = payload.seed
            participant.group_name = payload.group_name
        participant.status = decision
        participant.reviewed_at = utc_now()
        participant.reviewed_by = admin_id
        self.db.commit()
        self.db.refresh(participant)
        return participant

    def start(self, tournament_id: int) -> Tournament:
        tournament = self.require(tournament_id)
        if tournament.status == TournamentStatus.ACTIVE:
            return tournament
        if tournament.status != TournamentStatus.REGISTRATION:
            raise TournamentServiceError(409, "Only registration tournament can start")
        approved = (
            self.db.query(TournamentParticipant)
            .filter_by(
                tournament_id=tournament_id,
                status=TournamentParticipantStatus.APPROVED,
            )
            .count()
        )
        if approved < 2:
            raise TournamentServiceError(409, "At least two approved players required")
        scheduled = (
            self.db.query(TournamentMatch)
            .filter_by(tournament_id=tournament_id)
            .count()
        )
        if scheduled < 1:
            raise TournamentServiceError(409, "Schedule at least one match before start")
        tournament.status = TournamentStatus.ACTIVE
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def schedule_match(
        self,
        tournament_id: int,
        payload: TournamentMatchSchedule,
        admin_id: int,
    ) -> TournamentMatch:
        tournament = self.require(tournament_id)
        if tournament.status not in {
            TournamentStatus.REGISTRATION,
            TournamentStatus.ACTIVE,
        }:
            raise TournamentServiceError(409, "Tournament cannot accept matches")
        if payload.player_a_id == payload.player_b_id:
            raise TournamentServiceError(422, "Players must be different")
        scheduled_at = as_utc(payload.scheduled_at)
        if not as_utc(tournament.starts_at) <= scheduled_at <= as_utc(tournament.ends_at):
            raise TournamentServiceError(422, "Match must be inside tournament dates")
        participants = (
            self.db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.telegram_id.in_(
                    [payload.player_a_id, payload.player_b_id]
                ),
                TournamentParticipant.status == TournamentParticipantStatus.APPROVED,
            )
            .all()
        )
        if len(participants) != 2:
            raise TournamentServiceError(409, "Both players must be approved")
        if tournament.format == TournamentFormat.SINGLE_ELIMINATION:
            if payload.group_name is not None:
                raise TournamentServiceError(422, "Olympic match cannot have a group")
        else:
            groups = {participant.group_name for participant in participants}
            if payload.group_name and groups != {payload.group_name}:
                raise TournamentServiceError(422, "Group match players must share group")
        match = TournamentMatch(
            id=str(uuid4()),
            tournament_id=tournament_id,
            player_a_id=payload.player_a_id,
            player_b_id=payload.player_b_id,
            round_number=payload.round_number,
            round_name=payload.round_name.strip(),
            group_name=payload.group_name,
            scheduled_at=scheduled_at,
            status=TournamentMatchStatus.SCHEDULED,
            created_by=admin_id,
        )
        self.db.add(match)
        self.db.commit()
        self.db.refresh(match)
        return match

    def reschedule(
        self, tournament_id: int, match_id: str, scheduled_at: datetime
    ) -> TournamentMatch:
        tournament = self.require(tournament_id)
        match = (
            self.db.query(TournamentMatch)
            .filter_by(id=match_id, tournament_id=tournament_id)
            .one_or_none()
        )
        if match is None:
            raise TournamentServiceError(404, "Tournament match not found")
        if match.status not in {
            TournamentMatchStatus.SCHEDULED,
            TournamentMatchStatus.READY,
        }:
            raise TournamentServiceError(409, "Started match cannot be rescheduled")
        value = as_utc(scheduled_at)
        if not as_utc(tournament.starts_at) <= value <= as_utc(tournament.ends_at):
            raise TournamentServiceError(422, "Match must be inside tournament dates")
        match.scheduled_at = value
        self.db.commit()
        self.db.refresh(match)
        return match

    def matches(self, tournament_id: int) -> list[TournamentMatch]:
        self.require(tournament_id)
        return (
            self.db.query(TournamentMatch)
            .filter_by(tournament_id=tournament_id)
            .order_by(TournamentMatch.scheduled_at, TournamentMatch.round_number)
            .all()
        )
