from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.arena_v3 import (
    ArenaV3Match,
    ArenaV3SettlementStatus,
    ArenaV3Status,
)
from app.models.tournament import (
    Tournament,
    TournamentEntryMode,
    TournamentFormat,
    TournamentGroupMode,
    TournamentMatch,
    TournamentMatchStatus,
    TournamentParticipant,
    TournamentParticipantStatus,
    TournamentStatus,
)
from app.models.user import User
from app.models.wall_rush import GameTicketWallet
from app.schemas.tournament import (
    TournamentApplicationDecision,
    TournamentCreate,
    TournamentManualResult,
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
            .order_by(
                (Tournament.status == TournamentStatus.ACTIVE).desc(),
                Tournament.id.desc(),
            )
            .first()
        )

    def list_tournaments(
        self,
        *,
        statuses: set[TournamentStatus] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Tournament]:
        query = self.db.query(Tournament)
        if statuses:
            query = query.filter(Tournament.status.in_(statuses))
        return (
            query.order_by(Tournament.created_at.desc(), Tournament.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def require(self, tournament_id: int) -> Tournament:
        tournament = self.db.get(Tournament, tournament_id)
        if tournament is None:
            raise TournamentServiceError(404, "Tournament not found")
        return tournament

    def create(self, payload: TournamentCreate, admin_id: int) -> Tournament:
        registration_opens_at = as_utc(payload.registration_opens_at)
        registration_closes_at = as_utc(payload.registration_closes_at)
        starts_at = as_utc(payload.starts_at) if payload.starts_at else None
        ends_at = as_utc(payload.ends_at) if payload.ends_at else None
        if not registration_opens_at < registration_closes_at:
            raise TournamentServiceError(422, "Tournament dates are invalid")
        if starts_at is not None and not (
            registration_closes_at <= starts_at < ends_at
        ):
            raise TournamentServiceError(422, "Tournament dates are invalid")
        tournament = Tournament(
            name=payload.name.strip(),
            format=payload.format,
            status=TournamentStatus.REGISTRATION,
            max_participants=payload.max_participants,
            ticket_cost=payload.ticket_cost,
            entry_mode=payload.entry_mode,
            minimum_coin_purchase=payload.minimum_coin_purchase,
            duration_days=payload.duration_days,
            auto_start_when_full=payload.auto_start_when_full,
            announcement_channel_id=payload.announcement_channel_id,
            group_count=payload.group_count,
            group_size=payload.group_size,
            group_mode=payload.group_mode,
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
        if tournament.entry_mode == TournamentEntryMode.COIN_PURCHASE:
            raise TournamentServiceError(
                409,
                f"Bu turnirga bitta xaridda kamida "
                f"{tournament.minimum_coin_purchase} coin olish orqali avtomatik qo‘shilasiz",
            )
        if not (
            as_utc(tournament.registration_opens_at)
            <= now
            <= as_utc(tournament.registration_closes_at)
        ):
            raise TournamentServiceError(409, "Tournament registration window is closed")
        existing = self.participant(tournament_id, telegram_id)
        if existing is not None:
            return existing
        approved = (
            self.db.query(func.count(TournamentParticipant.id))
            .filter_by(
                tournament_id=tournament_id,
                status=TournamentParticipantStatus.APPROVED,
            )
            .scalar()
            or 0
        )
        if approved >= tournament.max_participants:
            raise TournamentServiceError(409, "Tournament capacity is full")
        self._require_ticket_balance(telegram_id, tournament.ticket_cost)
        wallet = self._wallet(telegram_id)
        wallet.tournament_tickets -= tournament.ticket_cost
        participant = TournamentParticipant(
            tournament_id=tournament_id,
            telegram_id=telegram_id,
            status=TournamentParticipantStatus.APPROVED,
            entry_ticket_state="SPENT",
            reviewed_at=now,
        )
        self.db.add(participant)
        self.db.commit()
        self.db.refresh(participant)
        return participant

    def applications(
        self,
        tournament_id: int,
        status: TournamentParticipantStatus | None,
        *,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
    ) -> list[TournamentParticipant]:
        self.require(tournament_id)
        query = self.db.query(TournamentParticipant).join(
            User, User.telegram_id == TournamentParticipant.telegram_id
        ).filter(TournamentParticipant.tournament_id == tournament_id)
        if status is not None:
            query = query.filter(TournamentParticipant.status == status)
        normalized_search = (search or "").strip()
        if normalized_search:
            pattern = f"%{normalized_search}%"
            query = query.filter(or_(
                User.username.ilike(pattern),
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
            ))
        return (
            query.order_by(TournamentParticipant.applied_at, TournamentParticipant.id)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def public_participants(
        self,
        tournament_id: int,
        *,
        limit: int = 100,
        offset: int = 0,
        group_name: str | None = None,
    ) -> list[TournamentParticipant]:
        """Return only players who were accepted into the public competition."""
        self.require(tournament_id)
        query = self.db.query(TournamentParticipant).filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.status.in_(
                    [
                        TournamentParticipantStatus.APPROVED,
                        TournamentParticipantStatus.ELIMINATED,
                        TournamentParticipantStatus.WITHDRAWN,
                    ]
                ),
            )
        if group_name is not None:
            query = query.filter(TournamentParticipant.group_name == group_name)
        return (
            query.order_by(
                TournamentParticipant.group_name,
                TournamentParticipant.seed,
                TournamentParticipant.applied_at,
            )
            .offset(offset)
            .limit(limit)
            .all()
        )

    def participant_count(self, tournament_id: int) -> int:
        return (
            self.db.query(func.count(TournamentParticipant.id))
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.status.in_([
                    TournamentParticipantStatus.APPROVED,
                    TournamentParticipantStatus.ELIMINATED,
                    TournamentParticipantStatus.WITHDRAWN,
                ]),
            )
            .scalar()
            or 0
        )

    def participants_by_telegram_ids(
        self, tournament_id: int, telegram_ids: set[int]
    ) -> list[TournamentParticipant]:
        if not telegram_ids:
            return []
        return (
            self.db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.telegram_id.in_(telegram_ids),
            )
            .all()
        )

    def match_count(self, tournament_id: int) -> int:
        return (
            self.db.query(func.count(TournamentMatch.id))
            .filter(TournamentMatch.tournament_id == tournament_id)
            .scalar()
            or 0
        )

    def current_round(self, tournament_id: int) -> int:
        return (
            self.db.query(func.max(TournamentMatch.round_number))
            .filter(TournamentMatch.tournament_id == tournament_id)
            .scalar()
            or 0
        )

    @staticmethod
    def total_rounds(participant_count: int) -> int:
        return max(1, (max(2, participant_count) - 1).bit_length())

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
            self._require_ticket_balance(
                participant.telegram_id, tournament.ticket_cost
            )
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

    @staticmethod
    def _group_label(index: int) -> str:
        value = index + 1
        label = ""
        while value:
            value, remainder = divmod(value - 1, 26)
            label = chr(65 + remainder) + label
        return label

    def start(self, tournament_id: int, admin_id: int | None = None) -> Tournament:
        tournament = (
            self.db.query(Tournament)
            .filter(Tournament.id == tournament_id)
            .with_for_update()
            .one_or_none()
        )
        if tournament is None:
            raise TournamentServiceError(404, "Tournament not found")
        if tournament.status == TournamentStatus.ACTIVE:
            return tournament
        if tournament.status != TournamentStatus.REGISTRATION:
            raise TournamentServiceError(409, "Only registration tournament can start")
        approved_rows = (
            self.db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.status == TournamentParticipantStatus.APPROVED,
            )
            .order_by(TournamentParticipant.applied_at, TournamentParticipant.id)
            .all()
        )
        if len(approved_rows) != tournament.max_participants:
            raise TournamentServiceError(
                409,
                f"Turnir boshlanishi uchun {tournament.max_participants} ta joy to‘lishi kerak",
            )
        self._activate(tournament, approved_rows, utc_now())
        self.db.commit()
        self.db.refresh(tournament)
        return tournament

    def _activate(
        self,
        tournament: Tournament,
        approved_rows: list[TournamentParticipant],
        started_at: datetime,
    ) -> None:
        if tournament.format == TournamentFormat.GROUP_PLAYOFF:
            if tournament.group_size not in {4, 8} or tournament.group_mode is None:
                raise TournamentServiceError(409, "Tournament group settings are missing")
            for index, participant in enumerate(approved_rows):
                participant.seed = index + 1
                participant.group_name = self._group_label(index // tournament.group_size)
        tournament.status = TournamentStatus.ACTIVE
        tournament.starts_at = started_at
        tournament.ends_at = started_at + timedelta(days=tournament.duration_days)
        tournament.updated_at = started_at

    def auto_register_coin_purchase(self, order) -> list[TournamentParticipant]:
        """Register one completed qualifying order in every open purchase tournament.

        The caller owns the transaction, so the ticket bonus and registrations are
        committed atomically. A purchase can qualify several concurrently open
        tournaments, while the per-tournament unique key prevents duplicate entry.
        """
        if (
            str(getattr(order, "product_type", "")).upper() != "COIN"
            or int(getattr(order, "coins_amount", 0) or 0) < 300
        ):
            return []
        now = utc_now()
        ids = [
            row[0]
            for row in self.db.query(Tournament.id)
            .filter(
                Tournament.status == TournamentStatus.REGISTRATION,
                Tournament.entry_mode == TournamentEntryMode.COIN_PURCHASE,
                Tournament.registration_opens_at <= now,
                Tournament.registration_closes_at >= now,
                Tournament.minimum_coin_purchase <= int(order.coins_amount),
            )
            .order_by(Tournament.id)
            .all()
        ]
        registrations: list[TournamentParticipant] = []
        for tournament_id in ids:
            tournament = (
                self.db.query(Tournament)
                .filter(Tournament.id == tournament_id)
                .with_for_update()
                .one()
            )
            existing = self.participant(tournament.id, order.telegram_id)
            if existing is not None:
                continue
            approved_rows = (
                self.db.query(TournamentParticipant)
                .filter(
                    TournamentParticipant.tournament_id == tournament.id,
                    TournamentParticipant.status == TournamentParticipantStatus.APPROVED,
                )
                .order_by(TournamentParticipant.applied_at, TournamentParticipant.id)
                .all()
            )
            if len(approved_rows) >= tournament.max_participants:
                continue
            participant = TournamentParticipant(
                tournament_id=tournament.id,
                telegram_id=order.telegram_id,
                status=TournamentParticipantStatus.APPROVED,
                entry_ticket_state="COIN_PURCHASE",
                qualification_order_id=order.id,
                qualification_coin_amount=int(order.coins_amount),
                reviewed_at=now,
            )
            self.db.add(participant)
            self.db.flush()
            registrations.append(participant)
            approved_rows.append(participant)
            if (
                tournament.auto_start_when_full
                and len(approved_rows) == tournament.max_participants
            ):
                self._activate(tournament, approved_rows, now)
        return registrations

    def finish_due(self, now: datetime | None = None) -> list[Tournament]:
        value = as_utc(now or utc_now())
        tournaments = (
            self.db.query(Tournament)
            .filter(
                Tournament.status == TournamentStatus.ACTIVE,
                Tournament.ends_at.is_not(None),
                Tournament.ends_at <= value,
            )
            .with_for_update(skip_locked=True)
            .all()
        )
        for tournament in tournaments:
            tournament.status = TournamentStatus.FINISHED
            tournament.updated_at = value
        if tournaments:
            self.db.commit()
        return tournaments

    def standings(self, tournament_id: int) -> list[TournamentParticipant]:
        self.require(tournament_id)
        return (
            self.db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.status.in_([
                    TournamentParticipantStatus.APPROVED,
                    TournamentParticipantStatus.ELIMINATED,
                ]),
            )
            .order_by(
                TournamentParticipant.points.desc(),
                TournamentParticipant.wins.desc(),
                (TournamentParticipant.goals_for - TournamentParticipant.goals_against).desc(),
                TournamentParticipant.goals_for.desc(),
                TournamentParticipant.played.asc(),
                TournamentParticipant.applied_at.asc(),
            )
            .all()
        )
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
        if tournament.starts_at is None or tournament.ends_at is None:
            raise TournamentServiceError(409, "Tournament has not started yet")
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
        duplicate = (
            self.db.query(TournamentMatch.id)
            .filter(
                TournamentMatch.tournament_id == tournament_id,
                TournamentMatch.group_name == payload.group_name,
                TournamentMatch.status != TournamentMatchStatus.CANCELLED,
                or_(
                    and_(
                        TournamentMatch.player_a_id == payload.player_a_id,
                        TournamentMatch.player_b_id == payload.player_b_id,
                    ),
                    and_(
                        TournamentMatch.player_a_id == payload.player_b_id,
                        TournamentMatch.player_b_id == payload.player_a_id,
                    ),
                ),
            )
            .first()
        )
        if duplicate is not None:
            raise TournamentServiceError(409, "These players already have a match")
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
        if tournament.starts_at is None or tournament.ends_at is None:
            raise TournamentServiceError(409, "Tournament has not started yet")
        if not as_utc(tournament.starts_at) <= value <= as_utc(tournament.ends_at):
            raise TournamentServiceError(422, "Match must be inside tournament dates")
        match.scheduled_at = value
        self.db.commit()
        self.db.refresh(match)
        return match

    def record_result(
        self,
        tournament_id: int,
        match_id: str,
        payload: TournamentManualResult,
        admin_id: int,
    ) -> TournamentMatch:
        tournament = self.require(tournament_id)
        match = (
            self.db.query(TournamentMatch)
            .filter_by(id=match_id, tournament_id=tournament_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise TournamentServiceError(404, "Tournament match not found")
        if match.status not in {
            TournamentMatchStatus.SCHEDULED,
            TournamentMatchStatus.FINISHED,
        }:
            raise TournamentServiceError(409, "Match result cannot be edited now")
        player_a, player_b = self._result_players(match)
        if match.status == TournamentMatchStatus.FINISHED:
            old_winner = (
                player_a if match.winner_id == player_a.telegram_id else player_b
            )
            old_loser = player_b if old_winner is player_a else player_a
            player_a.played = max(0, player_a.played - 1)
            player_b.played = max(0, player_b.played - 1)
            player_a.goals_for = max(0, player_a.goals_for - (match.player_a_score or 0))
            player_a.goals_against = max(0, player_a.goals_against - (match.player_b_score or 0))
            player_b.goals_for = max(0, player_b.goals_for - (match.player_b_score or 0))
            player_b.goals_against = max(0, player_b.goals_against - (match.player_a_score or 0))
            old_winner.wins = max(0, old_winner.wins - 1)
            old_loser.losses = max(0, old_loser.losses - 1)
            if (
                match.group_name is not None
                and tournament.group_mode == TournamentGroupMode.POINTS
            ):
                old_winner.points = max(0, old_winner.points - 3)
            else:
                old_loser.status = TournamentParticipantStatus.APPROVED
        winner, loser = (
            (player_a, player_b)
            if payload.player_a_score > payload.player_b_score
            else (player_b, player_a)
        )
        player_a.played += 1
        player_b.played += 1
        player_a.goals_for += payload.player_a_score
        player_a.goals_against += payload.player_b_score
        player_b.goals_for += payload.player_b_score
        player_b.goals_against += payload.player_a_score
        winner.wins += 1
        loser.losses += 1
        if (
            match.group_name is not None
            and tournament.group_mode == TournamentGroupMode.POINTS
        ):
            winner.points += 3
        else:
            loser.status = TournamentParticipantStatus.ELIMINATED
            winner.advanced_round = max(winner.advanced_round, match.round_number)
        match.player_a_score = payload.player_a_score
        match.player_b_score = payload.player_b_score
        match.winner_id = winner.telegram_id
        match.status = TournamentMatchStatus.FINISHED
        match.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(match)
        return match

    def finalize_groups(self, tournament_id: int) -> dict[str, int]:
        tournament = self.require(tournament_id)
        if (
            tournament.status != TournamentStatus.ACTIVE
            or tournament.format != TournamentFormat.GROUP_PLAYOFF
        ):
            raise TournamentServiceError(409, "Only active group tournament can be finalized")

        unfinished = (
            self.db.query(TournamentMatch.id)
            .filter(
                TournamentMatch.tournament_id == tournament_id,
                TournamentMatch.group_name.is_not(None),
                TournamentMatch.status.notin_([
                    TournamentMatchStatus.FINISHED,
                    TournamentMatchStatus.CANCELLED,
                ]),
            )
            .first()
        )
        if unfinished is not None:
            raise TournamentServiceError(409, "All group match results must be entered first")

        participants = (
            self.db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament_id,
                TournamentParticipant.group_name.is_not(None),
                TournamentParticipant.status.in_([
                    TournamentParticipantStatus.APPROVED,
                    TournamentParticipantStatus.ELIMINATED,
                ]),
            )
            .all()
        )
        groups: dict[str, list[TournamentParticipant]] = {}
        for participant in participants:
            groups.setdefault(participant.group_name, []).append(participant)
        if len(groups) != tournament.group_count:
            raise TournamentServiceError(409, "Tournament groups are incomplete")

        qualified = 0
        eliminated = 0
        for group_name, rows in groups.items():
            if len(rows) != tournament.group_size:
                raise TournamentServiceError(409, f"Group {group_name} is incomplete")
            if tournament.group_mode == TournamentGroupMode.POINTS:
                if any(row.played != tournament.group_size - 1 for row in rows):
                    raise TournamentServiceError(
                        409, f"Group {group_name} round-robin matches are incomplete"
                    )
                ranked = sorted(
                    rows,
                    key=lambda row: (
                        -row.points,
                        -row.wins,
                        -(row.goals_for - row.goals_against),
                        -row.goals_for,
                        row.seed or 0,
                    ),
                )
                advancing_ids = {
                    row.id for row in ranked[: tournament.qualifiers_per_group]
                }
                for row in rows:
                    if row.id in advancing_ids:
                        row.status = TournamentParticipantStatus.APPROVED
                        qualified += 1
                    else:
                        row.status = TournamentParticipantStatus.ELIMINATED
                        eliminated += 1
            else:
                survivors = [
                    row for row in rows
                    if row.status == TournamentParticipantStatus.APPROVED
                ]
                if len(survivors) != tournament.qualifiers_per_group:
                    raise TournamentServiceError(
                        409,
                        f"Group {group_name} must have exactly "
                        f"{tournament.qualifiers_per_group} survivors",
                    )
                qualified += len(survivors)
                eliminated += len(rows) - len(survivors)

        self.db.commit()
        return {
            "groups_finalized": len(groups),
            "qualified_players": qualified,
            "eliminated_players": eliminated,
        }

    def matches(
        self,
        tournament_id: int,
        *,
        round_number: int | None = None,
        status: TournamentMatchStatus | None = None,
        player_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TournamentMatch]:
        self.require(tournament_id)
        query = self.db.query(TournamentMatch).filter_by(tournament_id=tournament_id)
        if round_number is not None:
            query = query.filter(TournamentMatch.round_number == round_number)
        if status is not None:
            query = query.filter(TournamentMatch.status == status)
        if player_id is not None:
            query = query.filter(or_(
                TournamentMatch.player_a_id == player_id,
                TournamentMatch.player_b_id == player_id,
            ))
        return (
            query
            .order_by(TournamentMatch.scheduled_at, TournamentMatch.round_number)
            .offset(offset)
            .limit(limit)
            .all()
        )


    def _wallet(self, telegram_id: int) -> GameTicketWallet:
        wallet = (
            self.db.query(GameTicketWallet)
            .filter_by(telegram_id=telegram_id)
            .with_for_update()
            .one_or_none()
        )
        if wallet is None:
            wallet = GameTicketWallet(telegram_id=telegram_id)
            self.db.add(wallet)
            self.db.flush()
        return wallet

    def ticket_balance(self, telegram_id: int) -> int:
        wallet = self.db.get(GameTicketWallet, telegram_id)
        return wallet.tournament_tickets if wallet is not None else 0

    def _require_ticket_balance(self, telegram_id: int, ticket_cost: int) -> None:
        wallet = self._wallet(telegram_id)
        if wallet.tournament_tickets < ticket_cost:
            raise TournamentServiceError(
                409,
                f"Turnir uchun kamida {ticket_cost} ta Tournament Ticket kerak",
            )

    def open_match(self, tournament_id: int, match_id: str) -> TournamentMatch:
        tournament = self.require(tournament_id)
        match = (
            self.db.query(TournamentMatch)
            .filter_by(id=match_id, tournament_id=tournament_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise TournamentServiceError(404, "Tournament match not found")
        if match.arena_match_id is not None:
            return match
        if tournament.status != TournamentStatus.ACTIVE:
            raise TournamentServiceError(409, "Tournament must be active")
        if match.status != TournamentMatchStatus.SCHEDULED:
            raise TournamentServiceError(409, "Only scheduled match can be opened")
        users = {
            user.telegram_id: user
            for user in self.db.query(User)
            .filter(User.telegram_id.in_([match.player_a_id, match.player_b_id]))
            .all()
        }
        if len(users) != 2:
            raise TournamentServiceError(409, "Tournament player profile is missing")
        for player_id in (match.player_a_id, match.player_b_id):
            wallet = self._wallet(player_id)
            if wallet.tournament_tickets < tournament.ticket_cost:
                raise TournamentServiceError(
                    409,
                    f"Har ikki o‘yinchida kamida {tournament.ticket_cost} ta "
                    "Tournament Ticket bo‘lishi kerak",
                )
        for player_id in (match.player_a_id, match.player_b_id):
            wallet = self._wallet(player_id)
            wallet.tournament_tickets -= tournament.ticket_cost
            wallet.locked_tournament_tickets += tournament.ticket_cost
        def game_name(user: User) -> str:
            return (user.username or user.first_name or str(user.telegram_id))[:64]
        arena_match = ArenaV3Match(
            public_id=f"TRN{uuid4().hex[:20].upper()}",
            owner_id=match.player_a_id,
            opponent_id=match.player_b_id,
            owner_efootball_username=game_name(users[match.player_a_id]),
            opponent_efootball_username=game_name(users[match.player_b_id]),
            stake_efc=Decimal("0.00"),
            total_pool_efc=Decimal("0.00"),
            commission_efc=Decimal("0.00"),
            winner_reward_efc=Decimal("0.00"),
            match_type="TOURNAMENT",
            match_time_minutes=10,
            extra_time_enabled=False,
            penalties_enabled=True,
            status=ArenaV3Status.READY,
            settlement_status=ArenaV3SettlementStatus.NOT_STARTED,
            idempotency_key=f"tournament:{match.id}",
            request_fingerprint=match.id.replace("-", ""),
        )
        self.db.add(arena_match)
        self.db.flush()
        match.arena_match_id = arena_match.id
        match.player_a_ticket_state = "LOCKED"
        match.player_b_ticket_state = "LOCKED"
        match.status = TournamentMatchStatus.READY
        self.db.commit()
        self.db.refresh(match)
        return match

    def activate_arena_match(
        self, arena_match_id: int, *, commit: bool = True
    ) -> TournamentMatch:
        match = (
            self.db.query(TournamentMatch)
            .filter_by(arena_match_id=arena_match_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise TournamentServiceError(404, "Linked Tournament match is missing")
        if match.status == TournamentMatchStatus.PLAYING:
            return match
        if match.status != TournamentMatchStatus.READY:
            raise TournamentServiceError(409, "Tournament match is not ready")
        tournament = self.require(match.tournament_id)
        for player_id, state_name in (
            (match.player_a_id, "player_a_ticket_state"),
            (match.player_b_id, "player_b_ticket_state"),
        ):
            if getattr(match, state_name) != "LOCKED":
                raise TournamentServiceError(409, "Tournament Ticket is not locked")
            wallet = self._wallet(player_id)
            if wallet.locked_tournament_tickets < tournament.ticket_cost:
                raise TournamentServiceError(409, "Locked Tournament Ticket is missing")
            wallet.locked_tournament_tickets -= tournament.ticket_cost
            setattr(match, state_name, "SPENT")
        match.status = TournamentMatchStatus.PLAYING
        if commit:
            self.db.commit()
            self.db.refresh(match)
        else:
            self.db.flush()
        return match

    def cancel_before_start(
        self, arena_match_id: int, *, commit: bool = True
    ) -> TournamentMatch:
        match = (
            self.db.query(TournamentMatch)
            .filter_by(arena_match_id=arena_match_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise TournamentServiceError(404, "Linked Tournament match is missing")
        if match.status == TournamentMatchStatus.CANCELLED:
            return match
        if match.status != TournamentMatchStatus.READY:
            raise TournamentServiceError(409, "Started Tournament match cannot refund")
        tournament = self.require(match.tournament_id)
        for player_id, state_name in (
            (match.player_a_id, "player_a_ticket_state"),
            (match.player_b_id, "player_b_ticket_state"),
        ):
            if getattr(match, state_name) == "LOCKED":
                wallet = self._wallet(player_id)
                if wallet.locked_tournament_tickets < tournament.ticket_cost:
                    raise TournamentServiceError(409, "Locked Tournament Ticket is missing")
                wallet.locked_tournament_tickets -= tournament.ticket_cost
                wallet.tournament_tickets += tournament.ticket_cost
                setattr(match, state_name, "REFUNDED")
        match.status = TournamentMatchStatus.CANCELLED
        if commit:
            self.db.commit()
            self.db.refresh(match)
        else:
            self.db.flush()
        return match


    def _result_players(
        self, match: TournamentMatch
    ) -> tuple[TournamentParticipant, TournamentParticipant]:
        rows = (
            self.db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == match.tournament_id,
                TournamentParticipant.telegram_id.in_(
                    [match.player_a_id, match.player_b_id]
                ),
            )
            .with_for_update()
            .all()
        )
        by_id = {row.telegram_id: row for row in rows}
        player_a = by_id.get(match.player_a_id)
        player_b = by_id.get(match.player_b_id)
        if player_a is None or player_b is None:
            raise TournamentServiceError(409, "Tournament standings row is missing")
        return player_a, player_b

    def finish_arena_result(
        self,
        arena_match_id: int,
        *,
        player_a_score: int | None,
        player_b_score: int | None,
        cancelled: bool = False,
        commit: bool = True,
    ) -> TournamentMatch:
        match = (
            self.db.query(TournamentMatch)
            .filter_by(arena_match_id=arena_match_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise TournamentServiceError(404, "Linked Tournament match is missing")
        if match.status in {
            TournamentMatchStatus.FINISHED,
            TournamentMatchStatus.CANCELLED,
        }:
            return match
        if match.status != TournamentMatchStatus.PLAYING:
            raise TournamentServiceError(409, "Tournament match has not started")
        if cancelled:
            match.status = TournamentMatchStatus.CANCELLED
        else:
            if player_a_score is None or player_b_score is None:
                raise TournamentServiceError(422, "Tournament score is required")
            if player_a_score == player_b_score:
                raise TournamentServiceError(
                    409, "Equal scores are not allowed; penalties are required"
                )
            tournament = self.require(match.tournament_id)
            player_a, player_b = self._result_players(match)
            winner, loser = (
                (player_a, player_b)
                if player_a_score > player_b_score
                else (player_b, player_a)
            )
            match.winner_id = winner.telegram_id
            match.player_a_score = player_a_score
            match.player_b_score = player_b_score
            match.status = TournamentMatchStatus.FINISHED
            if (
                tournament.format == TournamentFormat.GROUP_PLAYOFF
                and match.group_name is not None
            ):
                for participant in (player_a, player_b):
                    participant.played += 1
                winner.wins += 1
                winner.points += 3
                loser.losses += 1
            else:
                winner.advanced_round = max(
                    winner.advanced_round, match.round_number
                )
                loser.status = TournamentParticipantStatus.ELIMINATED
        if commit:
            self.db.commit()
            self.db.refresh(match)
        else:
            self.db.flush()
        return match

    def revise_arena_result(
        self,
        arena_match_id: int,
        *,
        player_a_score: int | None,
        player_b_score: int | None,
        cancelled: bool = False,
        commit: bool = True,
    ) -> TournamentMatch:
        match = (
            self.db.query(TournamentMatch)
            .filter_by(arena_match_id=arena_match_id)
            .with_for_update()
            .one_or_none()
        )
        if match is None:
            raise TournamentServiceError(404, "Linked Tournament match is missing")
        if match.status not in {
            TournamentMatchStatus.FINISHED,
            TournamentMatchStatus.CANCELLED,
        }:
            raise TournamentServiceError(409, "Tournament result is not final")
        tournament = self.require(match.tournament_id)
        if match.status == TournamentMatchStatus.FINISHED:
            player_a, player_b = self._result_players(match)
            if (
                tournament.format == TournamentFormat.GROUP_PLAYOFF
                and match.group_name is not None
            ):
                old_winner = (
                    player_a if match.winner_id == player_a.telegram_id else player_b
                )
                old_loser = player_b if old_winner is player_a else player_a
                for participant in (player_a, player_b):
                    participant.played -= 1
                old_winner.wins -= 1
                old_winner.points -= 3
                old_loser.losses -= 1
            else:
                old_loser = (
                    player_b if match.winner_id == player_a.telegram_id else player_a
                )
                old_loser.status = TournamentParticipantStatus.APPROVED
                old_winner = player_a if old_loser is player_b else player_b
                old_winner.advanced_round = max(0, match.round_number - 1)
        match.winner_id = None
        match.player_a_score = None
        match.player_b_score = None
        match.status = TournamentMatchStatus.PLAYING
        return self.finish_arena_result(
            arena_match_id,
            player_a_score=player_a_score,
            player_b_score=player_b_score,
            cancelled=cancelled,
            commit=commit,
        )
