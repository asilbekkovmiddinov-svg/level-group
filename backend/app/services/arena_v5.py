from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import case, func, or_, select, union_all
from sqlalchemy.exc import IntegrityError

from app.core import config
from app.models.arena_v3 import (
    ArenaV3Match,
    ArenaV3MatchEvent,
    ArenaV3RankingPrize,
    ArenaV3SettlementStatus,
    ArenaV3Stats,
    ArenaV3Status,
    ArenaV4AdminReview,
    ArenaV4AdminReviewStatus,
    ArenaV4ReviewType,
    ArenaV5QueueEntry,
    ArenaV5ScreenshotSubmission,
)
from app.models.user import User
from app.models.wall_rush import (
    GameTicketLedger,
    GameTicketWallet,
    TicketKind,
)
from app.repositories.arena_v3 import ACTIVE_STATUSES, ArenaV3Repository
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3Forbidden,
    ArenaV3NotFound,
)
from app.services.arena_v3_state_machine import transition_arena_v3


ARENA_V5_TICKET_COST = 1
ARENA_V5_MATCH_TIME_MINUTES = 10
RELAY_STATUSES = (ArenaV3Status.PLAYING, ArenaV3Status.WAITING_ADMIN)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def season_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or _utc_now()
    configured_end = config.ARENA_V5_SEASON_END_AT
    if configured_end:
        try:
            end = datetime.fromisoformat(configured_end.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            return end - timedelta(days=7), end
        except ValueError:
            pass
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


class ArenaV5Service:
    def __init__(self, db):
        self.db = db
        self.repository = ArenaV3Repository(db)

    def _user(self, player_id: int, *, lock: bool = False) -> User:
        query = select(User).where(User.telegram_id == player_id)
        if lock:
            query = query.with_for_update()
        user = self.db.execute(query).scalar_one_or_none()
        if user is None:
            raise ArenaV3NotFound("Foydalanuvchi topilmadi")
        return user

    def _wallet(self, player_id: int, *, lock: bool = False) -> GameTicketWallet:
        query = select(GameTicketWallet).where(
            GameTicketWallet.telegram_id == player_id
        )
        if lock:
            query = query.with_for_update()
        wallet = self.db.execute(query).scalar_one_or_none()
        if wallet is None:
            wallet = GameTicketWallet(telegram_id=player_id)
            self.db.add(wallet)
            self.db.flush()
        return wallet

    def _ticket_balance(self, player_id: int) -> int:
        wallet = self._wallet(player_id)
        return int(wallet.tournament_tickets or 0)

    @staticmethod
    def _player(user: User | None, player_id: int, game_name: str | None) -> dict:
        return {
            "telegram_id": player_id,
            "telegram_username": user.username if user else None,
            "efootball_username": game_name or "O‘yinchi",
        }

    def match_response(self, match: ArenaV3Match) -> dict:
        owner = self.db.get(User, match.owner_id)
        opponent = self.db.get(User, match.opponent_id) if match.opponent_id else None
        bot_deep_link = None
        if match.flow_version >= 5 and match.bot_relay_token:
            bot_deep_link = (
                f"https://t.me/{config.TELEGRAM_BOT_USERNAME}"
                f"?start=arena_{match.bot_relay_token}"
            )
        return {
            "id": match.id,
            "public_id": match.public_id,
            "status": (
                match.status.value if hasattr(match.status, "value") else match.status
            ),
            "player_a": self._player(
                owner, match.owner_id, match.owner_efootball_username
            ),
            "player_b": (
                self._player(
                    opponent,
                    match.opponent_id,
                    match.opponent_efootball_username,
                )
                if match.opponent_id
                else None
            ),
            "score_a": match.owner_score,
            "score_b": match.opponent_score,
            "bot_deep_link": bot_deep_link,
            "created_at": match.created_at,
            "finished_at": match.finished_at,
            "legacy_flow": match.flow_version < 5,
        }

    def update_profile(self, player_id: int, efootball_username: str) -> dict:
        user = self._user(player_id, lock=True)
        user.efootball_username = efootball_username
        self.db.commit()
        return self.profile(player_id)

    def profile(self, player_id: int) -> dict:
        user = self._user(player_id)
        stats = self.db.get(ArenaV3Stats, player_id)
        return {
            "telegram_id": player_id,
            "telegram_username": user.username,
            "efootball_username": user.efootball_username,
            "games_played": int(stats.total_matches if stats else 0),
            "wins": int(stats.wins if stats else 0),
            "draws": int(stats.draws if stats else 0),
            "losses": int(stats.losses if stats else 0),
            "goals_for": int(stats.goals_for if stats else 0),
            "goals_against": int(stats.goals_against if stats else 0),
            "goal_difference": int(
                (stats.goals_for - stats.goals_against) if stats else 0
            ),
            "points": int(stats.points if stats else 0),
        }

    def state(self, player_id: int) -> dict:
        active = self.repository.find_active_for_player(player_id)
        balance = self._ticket_balance(player_id)
        if active is not None:
            return {
                "state": "MATCHED",
                "ticket_balance": balance,
                "match": self.match_response(active),
            }
        entry = self.db.get(ArenaV5QueueEntry, player_id)
        if entry is not None:
            return {
                "state": "SEARCHING",
                "ticket_balance": balance,
                "queued_at": entry.created_at,
            }
        return {"state": "IDLE", "ticket_balance": balance}

    def _spend_ticket(
        self, *, wallet: GameTicketWallet, player_id: int, match: ArenaV3Match
    ) -> None:
        key = f"arena-v5:match:{match.id}:entry:{player_id}"
        existing = self.db.execute(
            select(GameTicketLedger).where(GameTicketLedger.idempotency_key == key)
        ).scalar_one_or_none()
        if existing is not None:
            return
        if wallet.tournament_tickets < ARENA_V5_TICKET_COST:
            raise ArenaV3Conflict("Arena uchun kamida 1 ta Tournament Ticket kerak")
        wallet.tournament_tickets -= ARENA_V5_TICKET_COST
        self.db.add(GameTicketLedger(
            id=str(uuid4()),
            telegram_id=player_id,
            ticket_kind=TicketKind.TOURNAMENT,
            operation="ARENA_V5_ENTRY",
            amount=-ARENA_V5_TICKET_COST,
            match_id=None,
            idempotency_key=key,
            metadata_json={"arena_match_id": match.id, "flow_version": 5},
        ))

    def join_queue(self, player_id: int, idempotency_key: str) -> dict:
        requester = self._user(player_id, lock=True)
        active = self.repository.get_active_for_player(player_id)
        if active is not None:
            stale_entry = self.db.get(ArenaV5QueueEntry, player_id)
            if stale_entry is not None:
                self.db.delete(stale_entry)
                self.db.commit()
            return {
                **self.state(player_id),
                "matched_now": False,
            }
        name = " ".join((requester.efootball_username or "").strip().split())
        if not name:
            raise ArenaV3Conflict(
                "Avval Profil bo‘limida eFootball username kiriting"
            )
        requester_wallet = self._wallet(player_id, lock=True)
        if requester_wallet.tournament_tickets < ARENA_V5_TICKET_COST:
            stale = self.db.get(ArenaV5QueueEntry, player_id)
            if stale is not None:
                self.db.delete(stale)
                self.db.commit()
            raise ArenaV3Conflict("Arena uchun kamida 1 ta Tournament Ticket kerak")
        existing_entry = self.db.get(ArenaV5QueueEntry, player_id)
        if existing_entry is not None:
            return {
                "state": "SEARCHING",
                "ticket_balance": int(requester_wallet.tournament_tickets),
                "queued_at": existing_entry.created_at,
                "matched_now": False,
            }

        while True:
            candidate_entry = self.db.execute(
                select(ArenaV5QueueEntry)
                .where(ArenaV5QueueEntry.player_id != player_id)
                .order_by(
                    ArenaV5QueueEntry.created_at,
                    ArenaV5QueueEntry.player_id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            ).scalar_one_or_none()
            if candidate_entry is None:
                entry = ArenaV5QueueEntry(
                    player_id=player_id,
                    efootball_username=name,
                    idempotency_key=idempotency_key,
                )
                self.db.add(entry)
                try:
                    self.db.commit()
                except IntegrityError as exc:
                    self.db.rollback()
                    state = self.state(player_id)
                    if state["state"] in {"SEARCHING", "MATCHED"}:
                        return {**state, "matched_now": False}
                    raise ArenaV3Conflict("Matchmaking request conflicts") from exc
                self.db.refresh(entry)
                return {
                    "state": "SEARCHING",
                    "ticket_balance": int(requester_wallet.tournament_tickets),
                    "queued_at": entry.created_at,
                    "matched_now": False,
                }

            candidate_id = candidate_entry.player_id
            candidate = self._user(candidate_id, lock=True)
            candidate_active = self.repository.get_active_for_player(candidate_id)
            candidate_wallet = self._wallet(candidate_id, lock=True)
            if (
                candidate_active is not None
                or candidate_wallet.tournament_tickets < ARENA_V5_TICKET_COST
                or not candidate.efootball_username
            ):
                self.db.delete(candidate_entry)
                self.db.flush()
                continue

            match = ArenaV3Match(
                public_id=f"ARV5{uuid4().hex[:20].upper()}",
                owner_id=candidate_id,
                opponent_id=player_id,
                owner_efootball_username=candidate.efootball_username,
                opponent_efootball_username=name,
                stake_efc=Decimal("0"),
                total_pool_efc=Decimal("0"),
                commission_efc=Decimal("0"),
                winner_reward_efc=Decimal("0"),
                ticket_cost=ARENA_V5_TICKET_COST,
                owner_ticket_state="SPENT",
                opponent_ticket_state="SPENT",
                match_type="STANDARD",
                match_time_minutes=ARENA_V5_MATCH_TIME_MINUTES,
                extra_time_enabled=False,
                penalties_enabled=True,
                status=ArenaV3Status.PLAYING,
                playing_started_at=_utc_now(),
                settlement_status=ArenaV3SettlementStatus.NOT_STARTED,
                idempotency_key=f"arena-v5:{idempotency_key}",
                request_fingerprint=f"queue:{candidate_id}:{player_id}",
                flow_version=5,
                bot_relay_token=secrets.token_urlsafe(24),
            )
            self.repository.add_match(match)
            self._spend_ticket(
                wallet=candidate_wallet, player_id=candidate_id, match=match
            )
            self._spend_ticket(
                wallet=requester_wallet, player_id=player_id, match=match
            )
            self.db.delete(candidate_entry)
            self.repository.add_event(ArenaV3MatchEvent(
                match_id=match.id,
                event_type="ARENA_V5_MATCHED",
                from_status=None,
                to_status=ArenaV3Status.PLAYING.value,
                actor_type="SYSTEM",
                actor_id=player_id,
                idempotency_key=f"arena-v5:matched:{match.id}",
                event_metadata={"ticket_cost_per_player": ARENA_V5_TICKET_COST},
            ))
            try:
                self.db.commit()
            except IntegrityError as exc:
                self.db.rollback()
                raise ArenaV3Conflict("Parallel matchmaking request conflicts") from exc
            self.db.refresh(match)
            return {
                "state": "MATCHED",
                "ticket_balance": int(requester_wallet.tournament_tickets),
                "match": self.match_response(match),
                "matched_now": True,
            }

    def cancel_queue(self, player_id: int) -> dict:
        entry = self.db.execute(
            select(ArenaV5QueueEntry)
            .where(ArenaV5QueueEntry.player_id == player_id)
            .with_for_update()
        ).scalar_one_or_none()
        self._user(player_id, lock=True)
        if self.repository.get_active_for_player(player_id) is not None:
            raise ArenaV3Conflict("Raqib topilgan matchni queue sifatida bekor qilib bo‘lmaydi")
        if entry is not None:
            self.db.delete(entry)
        self.db.commit()
        return {**self.state(player_id), "matched_now": False}

    def config_response(self, player_id: int) -> dict:
        start, end = season_window()
        prize = self.db.get(ArenaV3RankingPrize, "weekly")
        return {
            "ticket_cost": ARENA_V5_TICKET_COST,
            "ticket_balance": self._ticket_balance(player_id),
            "season_name": config.ARENA_V5_SEASON_NAME or "Haftalik Arena",
            "season_start_at": start,
            "season_end_at": end,
            "prize_text": prize.prize_text if prize else None,
        }

    def ranking(self, *, limit: int, offset: int) -> dict:
        start, end = season_window()
        filters = (
            ArenaV3Match.flow_version == 5,
            ArenaV3Match.status == ArenaV3Status.FINISHED,
            ArenaV3Match.finished_at >= start,
            ArenaV3Match.finished_at < end,
            ArenaV3Match.owner_score.is_not(None),
            ArenaV3Match.opponent_score.is_not(None),
        )
        owner = select(
            ArenaV3Match.owner_id.label("player_id"),
            case((ArenaV3Match.owner_score > ArenaV3Match.opponent_score, 1), else_=0).label("wins"),
            case((ArenaV3Match.owner_score == ArenaV3Match.opponent_score, 1), else_=0).label("draws"),
            case((ArenaV3Match.owner_score < ArenaV3Match.opponent_score, 1), else_=0).label("losses"),
            ArenaV3Match.owner_score.label("goals_for"),
            ArenaV3Match.opponent_score.label("goals_against"),
            case(
                (ArenaV3Match.owner_score > ArenaV3Match.opponent_score, 3),
                (ArenaV3Match.owner_score == ArenaV3Match.opponent_score, 1),
                else_=0,
            ).label("points"),
        ).where(*filters)
        opponent = select(
            ArenaV3Match.opponent_id.label("player_id"),
            case((ArenaV3Match.opponent_score > ArenaV3Match.owner_score, 1), else_=0).label("wins"),
            case((ArenaV3Match.opponent_score == ArenaV3Match.owner_score, 1), else_=0).label("draws"),
            case((ArenaV3Match.opponent_score < ArenaV3Match.owner_score, 1), else_=0).label("losses"),
            ArenaV3Match.opponent_score.label("goals_for"),
            ArenaV3Match.owner_score.label("goals_against"),
            case(
                (ArenaV3Match.opponent_score > ArenaV3Match.owner_score, 3),
                (ArenaV3Match.opponent_score == ArenaV3Match.owner_score, 1),
                else_=0,
            ).label("points"),
        ).where(*filters)
        rows = union_all(owner, opponent).subquery()
        aggregated = (
            select(
                rows.c.player_id,
                func.count().label("games_played"),
                func.sum(rows.c.wins).label("wins"),
                func.sum(rows.c.draws).label("draws"),
                func.sum(rows.c.losses).label("losses"),
                func.sum(rows.c.goals_for).label("goals_for"),
                func.sum(rows.c.goals_against).label("goals_against"),
                func.sum(rows.c.points).label("points"),
            )
            .group_by(rows.c.player_id)
            .subquery()
        )
        result = self.db.execute(
            select(aggregated, User)
            .join(User, User.telegram_id == aggregated.c.player_id)
            .order_by(
                aggregated.c.points.desc(),
                (aggregated.c.goals_for - aggregated.c.goals_against).desc(),
                aggregated.c.goals_for.desc(),
                aggregated.c.wins.desc(),
                aggregated.c.player_id.asc(),
            )
            .offset(offset)
            .limit(limit)
        ).all()
        players = []
        for index, row in enumerate(result, start=offset + 1):
            players.append({
                "rank": index,
                "efootball_username": row.User.efootball_username
                or row.User.username
                or "O‘yinchi",
                "games_played": int(row.games_played or 0),
                "wins": int(row.wins or 0),
                "draws": int(row.draws or 0),
                "losses": int(row.losses or 0),
                "goals_for": int(row.goals_for or 0),
                "goals_against": int(row.goals_against or 0),
                "goal_difference": int((row.goals_for or 0) - (row.goals_against or 0)),
                "points": int(row.points or 0),
            })
        prize = self.db.get(ArenaV3RankingPrize, "weekly")
        return {
            "season_name": config.ARENA_V5_SEASON_NAME or "Haftalik Arena",
            "season_start_at": start,
            "season_end_at": end,
            "prize_text": prize.prize_text if prize else None,
            "players": players,
        }

    def history(self, player_id: int, *, limit: int, offset: int) -> list[dict]:
        matches = self.db.execute(
            select(ArenaV3Match)
            .where(
                ArenaV3Match.flow_version == 5,
                ArenaV3Match.status == ArenaV3Status.FINISHED,
                or_(
                    ArenaV3Match.owner_id == player_id,
                    ArenaV3Match.opponent_id == player_id,
                ),
            )
            .order_by(ArenaV3Match.finished_at.desc(), ArenaV3Match.id.desc())
            .offset(offset)
            .limit(limit)
        ).scalars().all()
        items = []
        for match in matches:
            is_owner = match.owner_id == player_id
            own_score = match.owner_score if is_owner else match.opponent_score
            opponent_score = match.opponent_score if is_owner else match.owner_score
            if own_score > opponent_score:
                result, points = "WIN", 3
            elif own_score == opponent_score:
                result, points = "DRAW", 1
            else:
                result, points = "LOSS", 0
            items.append({
                "match_id": match.id,
                "public_id": match.public_id,
                "opponent_efootball_username": (
                    match.opponent_efootball_username
                    if is_owner else match.owner_efootball_username
                ),
                "own_score": own_score,
                "opponent_score": opponent_score,
                "result": result,
                "points": points,
                "finished_at": match.finished_at,
            })
        return items

    def active_internal(self, player_id: int) -> dict:
        match = self.repository.find_active_for_player(player_id)
        if match is None or match.flow_version < 5:
            return {"match": None, "opponent_telegram_id": None, "relay_allowed": False}
        opponent_id = (
            match.opponent_id if match.owner_id == player_id else match.owner_id
        )
        return {
            "match": self.match_response(match),
            "opponent_telegram_id": opponent_id,
            "relay_allowed": match.status in RELAY_STATUSES,
        }

    def validate_relay(self, player_id: int, token: str) -> dict:
        match = self.db.execute(
            select(ArenaV3Match).where(ArenaV3Match.bot_relay_token == token)
        ).scalar_one_or_none()
        if match is None:
            raise ArenaV3NotFound("Arena match deep-link topilmadi")
        if player_id not in {match.owner_id, match.opponent_id}:
            raise ArenaV3Forbidden("Siz bu Arena match ishtirokchisi emassiz")
        if match.flow_version < 5 or match.status not in RELAY_STATUSES:
            raise ArenaV3Conflict("Bu Arena match uchun relay chat yopilgan")
        opponent_id = (
            match.opponent_id if match.owner_id == player_id else match.owner_id
        )
        return {
            "match": self.match_response(match),
            "opponent_telegram_id": opponent_id,
            "relay_allowed": True,
        }

    def prepare_submission(
        self, *, player_id: int, telegram_file_id: str, telegram_message_id: int
    ) -> dict:
        match = self.repository.get_active_for_player(player_id)
        if match is None or match.flow_version < 5:
            raise ArenaV3NotFound("Aktiv Arena V5 match topilmadi")
        if player_id not in {match.owner_id, match.opponent_id}:
            raise ArenaV3Forbidden("Siz bu match ishtirokchisi emassiz")
        if match.status not in RELAY_STATUSES:
            raise ArenaV3Conflict("Bu match screenshot qabul qilmaydi")
        submission = self.db.execute(
            select(ArenaV5ScreenshotSubmission)
            .where(
                ArenaV5ScreenshotSubmission.match_id == match.id,
                ArenaV5ScreenshotSubmission.player_id == player_id,
            )
            .with_for_update()
        ).scalar_one_or_none()
        if submission is None:
            submission = ArenaV5ScreenshotSubmission(
                match_id=match.id,
                player_id=player_id,
                telegram_file_id=telegram_file_id,
                telegram_message_id=telegram_message_id,
                delivery_status="PENDING",
            )
            self.db.add(submission)
            self.db.flush()
        elif submission.delivery_status != "SENT":
            submission.telegram_file_id = telegram_file_id
            submission.telegram_message_id = telegram_message_id
            submission.delivery_status = "PENDING"
            submission.last_error = None
        self.db.commit()
        self.db.refresh(submission)
        user = self._user(player_id)
        game_name = (
            match.owner_efootball_username
            if match.owner_id == player_id
            else match.opponent_efootball_username
        )
        return {
            "submission_id": submission.id,
            "delivery_status": submission.delivery_status,
            "should_deliver": submission.delivery_status != "SENT",
            "match": self.match_response(match),
            "submitted_by": self._player(user, player_id, game_name),
        }

    def complete_submission(
        self, submission_id: int, admin_channel_message_id: int
    ) -> dict:
        submission = self.db.execute(
            select(ArenaV5ScreenshotSubmission)
            .where(ArenaV5ScreenshotSubmission.id == submission_id)
            .with_for_update()
        ).scalar_one_or_none()
        if submission is None:
            raise ArenaV3NotFound("Arena screenshot submission topilmadi")
        match = self.repository.get_match_for_update(submission.match_id)
        if match is None:
            raise ArenaV3NotFound("Arena match topilmadi")
        if submission.delivery_status != "SENT":
            submission.delivery_status = "SENT"
            submission.admin_channel_message_id = admin_channel_message_id
            submission.delivered_at = _utc_now()
            if match.admin_channel_message_id is None:
                match.admin_channel_message_id = admin_channel_message_id
            if match.status == ArenaV3Status.PLAYING:
                from_status = ArenaV3Status.PLAYING
                transition_arena_v3(match, ArenaV3Status.WAITING_ADMIN)
                if self.repository.get_initial_admin_review(
                    match.id, match.result_version
                ) is None:
                    self.repository.add_admin_review(ArenaV4AdminReview(
                        match_id=match.id,
                        review_type=ArenaV4ReviewType.INITIAL,
                        status=ArenaV4AdminReviewStatus.PENDING,
                        result_version=match.result_version,
                        expected_match_version=match.version,
                    ))
                self.repository.add_event(ArenaV3MatchEvent(
                    match_id=match.id,
                    event_type="ARENA_V5_SCREENSHOT_DELIVERED",
                    from_status=from_status.value,
                    to_status=ArenaV3Status.WAITING_ADMIN.value,
                    actor_type="USER",
                    actor_id=submission.player_id,
                    idempotency_key=f"arena-v5:submission:{submission.id}:delivered",
                    event_metadata={
                        "admin_channel_message_id": admin_channel_message_id
                    },
                ))
            self.db.commit()
        user = self._user(submission.player_id)
        game_name = (
            match.owner_efootball_username
            if match.owner_id == submission.player_id
            else match.opponent_efootball_username
        )
        return {
            "submission_id": submission.id,
            "delivery_status": submission.delivery_status,
            "should_deliver": False,
            "match": self.match_response(match),
            "submitted_by": self._player(
                user, submission.player_id, game_name
            ),
        }

    def fail_submission(self, submission_id: int, error: str) -> dict:
        submission = self.db.execute(
            select(ArenaV5ScreenshotSubmission)
            .where(ArenaV5ScreenshotSubmission.id == submission_id)
            .with_for_update()
        ).scalar_one_or_none()
        if submission is None:
            raise ArenaV3NotFound("Arena screenshot submission topilmadi")
        if submission.delivery_status != "SENT":
            submission.delivery_status = "FAILED"
            submission.last_error = error
            self.db.commit()
        match = self.repository.get_match(submission.match_id)
        user = self._user(submission.player_id)
        game_name = (
            match.owner_efootball_username
            if match.owner_id == submission.player_id
            else match.opponent_efootball_username
        )
        return {
            "submission_id": submission.id,
            "delivery_status": submission.delivery_status,
            "should_deliver": submission.delivery_status != "SENT",
            "match": self.match_response(match),
            "submitted_by": self._player(
                user, submission.player_id, game_name
            ),
        }
