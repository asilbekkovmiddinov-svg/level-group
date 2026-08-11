from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import case, or_, text
from sqlalchemy.orm import Session

from app.models.division import (
    DivisionMatch,
    DivisionMatchStatus,
    DivisionParticipant,
    DivisionParticipantStatus,
    DivisionSeason,
    DivisionSeasonStatus,
    DivisionTicketLedger,
    DivisionTicketState,
)
from app.models.user import User
from app.models.wall_rush import GameTicketWallet
from app.schemas.division import DivisionSeasonCreate


SEASON_DURATION_DAYS = 30


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DivisionServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class DivisionService:
    def __init__(self, db: Session):
        self.db = db

    def current_season(self) -> DivisionSeason | None:
        priority = case(
            (DivisionSeason.status == DivisionSeasonStatus.ACTIVE, 0),
            (DivisionSeason.status == DivisionSeasonStatus.REGISTRATION, 1),
            else_=2,
        )
        return (
            self.db.query(DivisionSeason)
            .filter(
                DivisionSeason.status.in_(
                    [
                        DivisionSeasonStatus.REGISTRATION,
                        DivisionSeasonStatus.ACTIVE,
                    ]
                )
            )
            .order_by(priority, DivisionSeason.id.desc())
            .first()
        )

    def create_season(
        self, payload: DivisionSeasonCreate, admin_id: int
    ) -> DivisionSeason:
        if self.current_season() is not None:
            raise DivisionServiceError(
                409, "An active or registration Division season already exists"
            )
        registration_opens_at = as_utc(payload.registration_opens_at)
        registration_closes_at = as_utc(payload.registration_closes_at)
        starts_at = as_utc(payload.starts_at)
        if not registration_opens_at < registration_closes_at <= starts_at:
            raise DivisionServiceError(
                422,
                "Registration must open before it closes and close no later than season start",
            )
        season = DivisionSeason(
            name=payload.name.strip(),
            status=DivisionSeasonStatus.REGISTRATION,
            duration_days=SEASON_DURATION_DAYS,
            ticket_cost=1,
            points_for_win=3,
            points_for_loss=0,
            registration_opens_at=registration_opens_at,
            registration_closes_at=registration_closes_at,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(days=SEASON_DURATION_DAYS),
            created_by=admin_id,
        )
        self.db.add(season)
        self.db.commit()
        self.db.refresh(season)
        return season

    def require_season(self, season_id: int) -> DivisionSeason:
        season = self.db.get(DivisionSeason, season_id)
        if season is None:
            raise DivisionServiceError(404, "Division season not found")
        return season

    def start_season(self, season_id: int) -> DivisionSeason:
        season = self.require_season(season_id)
        if season.status == DivisionSeasonStatus.ACTIVE:
            return season
        if season.status != DivisionSeasonStatus.REGISTRATION:
            raise DivisionServiceError(409, "Only registration season can be started")
        season.status = DivisionSeasonStatus.ACTIVE
        self.db.commit()
        self.db.refresh(season)
        return season

    def finish_season(self, season_id: int) -> DivisionSeason:
        season = self.require_season(season_id)
        if season.status == DivisionSeasonStatus.FINISHED:
            return season
        if season.status != DivisionSeasonStatus.ACTIVE:
            raise DivisionServiceError(409, "Only active season can be finished")
        season.status = DivisionSeasonStatus.FINISHED
        self.db.commit()
        self.db.refresh(season)
        return season

    def participant(
        self, season_id: int, telegram_id: int
    ) -> DivisionParticipant | None:
        return (
            self.db.query(DivisionParticipant)
            .filter(
                DivisionParticipant.season_id == season_id,
                DivisionParticipant.telegram_id == telegram_id,
            )
            .one_or_none()
        )

    def apply(self, telegram_id: int) -> DivisionParticipant:
        season = self.current_season()
        if season is None or season.status != DivisionSeasonStatus.REGISTRATION:
            raise DivisionServiceError(409, "Division registration is not open")
        now = utc_now()
        if not (
            as_utc(season.registration_opens_at)
            <= now
            <= as_utc(season.registration_closes_at)
        ):
            raise DivisionServiceError(409, "Division registration window is closed")
        existing = self.participant(season.id, telegram_id)
        if existing is not None:
            return existing
        participant = DivisionParticipant(
            season_id=season.id,
            telegram_id=telegram_id,
            status=DivisionParticipantStatus.PENDING,
        )
        self.db.add(participant)
        self.db.commit()
        self.db.refresh(participant)
        return participant

    def overview(self, telegram_id: int) -> dict:
        season = self.current_season()
        return {
            "season": season,
            "participant": (
                self.participant(season.id, telegram_id) if season is not None else None
            ),
        }

    def list_applications(
        self,
        season_id: int,
        status: DivisionParticipantStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[DivisionSeason, list[DivisionParticipant], int]:
        season = self.require_season(season_id)
        query = self.db.query(DivisionParticipant).filter(
            DivisionParticipant.season_id == season_id
        )
        if status is not None:
            query = query.filter(DivisionParticipant.status == status)
        total = query.count()
        items = (
            query.order_by(DivisionParticipant.applied_at, DivisionParticipant.id)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return season, items, total

    def review_application(
        self,
        season_id: int,
        participant_id: int,
        decision: DivisionParticipantStatus,
        admin_id: int,
    ) -> DivisionParticipant:
        if decision not in {
            DivisionParticipantStatus.APPROVED,
            DivisionParticipantStatus.REJECTED,
        }:
            raise DivisionServiceError(422, "Invalid application decision")
        participant = (
            self.db.query(DivisionParticipant)
            .filter(
                DivisionParticipant.id == participant_id,
                DivisionParticipant.season_id == season_id,
            )
            .one_or_none()
        )
        if participant is None:
            raise DivisionServiceError(404, "Division application not found")
        if participant.status == decision:
            return participant
        if participant.status != DivisionParticipantStatus.PENDING:
            raise DivisionServiceError(409, "Division application is already reviewed")
        participant.status = decision
        participant.reviewed_at = utc_now()
        participant.reviewed_by = admin_id
        self.db.commit()
        self.db.refresh(participant)
        return participant

    def standings(
        self, season_id: int | None, limit: int, offset: int
    ) -> tuple[DivisionSeason, list[dict], int]:
        season = (
            self.require_season(season_id)
            if season_id is not None
            else self.current_season()
        )
        if season is None:
            raise DivisionServiceError(404, "Division season not found")
        query = (
            self.db.query(DivisionParticipant, User)
            .join(User, User.telegram_id == DivisionParticipant.telegram_id)
            .filter(
                DivisionParticipant.season_id == season.id,
                DivisionParticipant.status == DivisionParticipantStatus.APPROVED,
            )
        )
        total = query.count()
        rows = (
            query.order_by(
                DivisionParticipant.points.desc(),
                DivisionParticipant.wins.desc(),
                (
                    DivisionParticipant.goals_for
                    - DivisionParticipant.goals_against
                ).desc(),
                DivisionParticipant.goals_for.desc(),
                DivisionParticipant.applied_at,
                DivisionParticipant.id,
            )
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = []
        for index, (participant, user) in enumerate(rows, start=offset + 1):
            items.append(
                {
                    "rank": index,
                    "telegram_id": participant.telegram_id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "matches_played": participant.matches_played,
                    "wins": participant.wins,
                    "losses": participant.losses,
                    "points": participant.points,
                    "goals_for": participant.goals_for,
                    "goals_against": participant.goals_against,
                    "goal_difference": (
                        participant.goals_for - participant.goals_against
                    ),
                }
            )
        return season, items, total


    def _serialize_matchmaking(self, season_id: int) -> None:
        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            self.db.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": 730000000 + season_id},
            )

    def active_match(
        self, season_id: int, telegram_id: int
    ) -> DivisionMatch | None:
        return (
            self.db.query(DivisionMatch)
            .filter(
                DivisionMatch.season_id == season_id,
                DivisionMatch.status.in_(
                    [
                        DivisionMatchStatus.WAITING,
                        DivisionMatchStatus.MATCHED,
                        DivisionMatchStatus.ACTIVE,
                    ]
                ),
                or_(
                    DivisionMatch.player_a_id == telegram_id,
                    DivisionMatch.player_b_id == telegram_id,
                ),
            )
            .order_by(DivisionMatch.created_at.desc())
            .first()
        )

    def _locked_wallet(self, telegram_id: int) -> GameTicketWallet:
        wallet = (
            self.db.query(GameTicketWallet)
            .filter(GameTicketWallet.telegram_id == telegram_id)
            .with_for_update()
            .one_or_none()
        )
        if wallet is None:
            wallet = GameTicketWallet(
                telegram_id=telegram_id,
                game_tickets=0,
                locked_game_tickets=0,
                tournament_tickets=0,
                locked_tournament_tickets=0,
            )
            self.db.add(wallet)
            self.db.flush()
        return wallet

    def _ticket_ledger(
        self,
        *,
        match_id: str,
        telegram_id: int,
        operation: str,
        available_delta: int,
        locked_delta: int,
    ) -> None:
        key = f"division:{match_id}:{telegram_id}:{operation.lower()}"
        existing = (
            self.db.query(DivisionTicketLedger)
            .filter(DivisionTicketLedger.idempotency_key == key)
            .one_or_none()
        )
        if existing is not None:
            return
        self.db.add(
            DivisionTicketLedger(
                id=str(uuid4()),
                telegram_id=telegram_id,
                match_id=match_id,
                operation=operation,
                available_delta=available_delta,
                locked_delta=locked_delta,
                idempotency_key=key,
            )
        )

    def _lock_tournament_ticket(
        self, match_id: str, telegram_id: int
    ) -> None:
        wallet = self._locked_wallet(telegram_id)
        if wallet.tournament_tickets < 1:
            raise DivisionServiceError(409, "Tournament Ticket is required")
        wallet.tournament_tickets -= 1
        wallet.locked_tournament_tickets += 1
        self._ticket_ledger(
            match_id=match_id,
            telegram_id=telegram_id,
            operation="LOCK",
            available_delta=-1,
            locked_delta=1,
        )

    def _refund_tournament_ticket(
        self, match_id: str, telegram_id: int
    ) -> None:
        wallet = self._locked_wallet(telegram_id)
        if wallet.locked_tournament_tickets < 1:
            raise DivisionServiceError(409, "Locked Tournament Ticket is missing")
        wallet.locked_tournament_tickets -= 1
        wallet.tournament_tickets += 1
        self._ticket_ledger(
            match_id=match_id,
            telegram_id=telegram_id,
            operation="REFUND",
            available_delta=1,
            locked_delta=-1,
        )

    def _spend_tournament_ticket(
        self, match_id: str, telegram_id: int
    ) -> None:
        wallet = self._locked_wallet(telegram_id)
        if wallet.locked_tournament_tickets < 1:
            raise DivisionServiceError(409, "Locked Tournament Ticket is missing")
        wallet.locked_tournament_tickets -= 1
        self._ticket_ledger(
            match_id=match_id,
            telegram_id=telegram_id,
            operation="SPEND",
            available_delta=0,
            locked_delta=-1,
        )

    def join_matchmaking(self, telegram_id: int) -> DivisionMatch:
        season = self.current_season()
        if season is None or season.status != DivisionSeasonStatus.ACTIVE:
            raise DivisionServiceError(409, "Division season is not active")
        participant = self.participant(season.id, telegram_id)
        if (
            participant is None
            or participant.status != DivisionParticipantStatus.APPROVED
        ):
            raise DivisionServiceError(403, "Approved Division participant required")

        self._serialize_matchmaking(season.id)
        existing = self.active_match(season.id, telegram_id)
        if existing is not None:
            return existing

        opponent_match = (
            self.db.query(DivisionMatch)
            .filter(
                DivisionMatch.season_id == season.id,
                DivisionMatch.status == DivisionMatchStatus.WAITING,
                DivisionMatch.player_b_id.is_(None),
                DivisionMatch.player_a_id != telegram_id,
            )
            .order_by(DivisionMatch.created_at, DivisionMatch.id)
            .with_for_update()
            .first()
        )
        if opponent_match is None:
            match = DivisionMatch(
                id=str(uuid4()),
                season_id=season.id,
                player_a_id=telegram_id,
                status=DivisionMatchStatus.WAITING,
                player_a_ticket_state=DivisionTicketState.LOCKED,
            )
            self.db.add(match)
            self._lock_tournament_ticket(match.id, telegram_id)
        else:
            match = opponent_match
            self._lock_tournament_ticket(match.id, telegram_id)
            match.player_b_id = telegram_id
            match.player_b_ticket_state = DivisionTicketState.LOCKED
            match.status = DivisionMatchStatus.MATCHED
            match.matched_at = utc_now()

        self.db.commit()
        self.db.refresh(match)
        return match

    def cancel_waiting_match(
        self, match_id: str, telegram_id: int
    ) -> DivisionMatch:
        match = (
            self.db.query(DivisionMatch)
            .filter(DivisionMatch.id == match_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None or match.player_a_id != telegram_id:
            raise DivisionServiceError(404, "Division match not found")
        if (
            match.status != DivisionMatchStatus.WAITING
            or match.player_b_id is not None
        ):
            raise DivisionServiceError(409, "Only waiting search can be cancelled")
        if match.player_a_ticket_state == DivisionTicketState.LOCKED:
            self._refund_tournament_ticket(match.id, telegram_id)
            match.player_a_ticket_state = DivisionTicketState.REFUNDED
        match.status = DivisionMatchStatus.CANCELLED
        match.cancel_reason = "PLAYER_LEFT_QUEUE"
        match.finished_at = utc_now()
        self.db.commit()
        self.db.refresh(match)
        return match

    def cancel_before_start(
        self, match_id: str, reason: str
    ) -> DivisionMatch:
        match = (
            self.db.query(DivisionMatch)
            .filter(DivisionMatch.id == match_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise DivisionServiceError(404, "Division match not found")
        if match.status != DivisionMatchStatus.MATCHED:
            raise DivisionServiceError(409, "Division match cannot be refunded")
        players = (
            (match.player_a_id, "player_a_ticket_state"),
            (match.player_b_id, "player_b_ticket_state"),
        )
        for player_id, state_attribute in players:
            if (
                player_id is not None
                and getattr(match, state_attribute) == DivisionTicketState.LOCKED
            ):
                self._refund_tournament_ticket(match.id, player_id)
                setattr(match, state_attribute, DivisionTicketState.REFUNDED)
        match.status = DivisionMatchStatus.CANCELLED
        match.cancel_reason = reason
        match.finished_at = utc_now()
        self.db.commit()
        self.db.refresh(match)
        return match

    def activate_match(self, match_id: str) -> DivisionMatch:
        match = (
            self.db.query(DivisionMatch)
            .filter(DivisionMatch.id == match_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise DivisionServiceError(404, "Division match not found")
        if match.status == DivisionMatchStatus.ACTIVE:
            return match
        if (
            match.status != DivisionMatchStatus.MATCHED
            or match.player_b_id is None
        ):
            raise DivisionServiceError(409, "Matched opponent is required")
        for player_id, state_attribute in (
            (match.player_a_id, "player_a_ticket_state"),
            (match.player_b_id, "player_b_ticket_state"),
        ):
            if getattr(match, state_attribute) != DivisionTicketState.LOCKED:
                raise DivisionServiceError(409, "Tournament Ticket is not locked")
            self._spend_tournament_ticket(match.id, player_id)
            setattr(match, state_attribute, DivisionTicketState.SPENT)
        match.status = DivisionMatchStatus.ACTIVE
        match.started_at = utc_now()
        self.db.commit()
        self.db.refresh(match)
        return match
