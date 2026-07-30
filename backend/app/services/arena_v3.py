import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import config
from app.models.arena_v3 import (
    ArenaV3Match,
    ArenaV3MatchEvent,
    ArenaV3MatchScreenshot,
    ArenaV3EvidenceStatus,
    ArenaV3SettlementStatus,
    ArenaV3Status,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3_state_machine import (
    ArenaV3InvalidTransition,
    transition_arena_v3,
)


SCREENSHOT_UPLOAD_WINDOW_SECONDS = 300


MATCH_COMMISSION_PERCENT = Decimal("5.00")
SUPPORTED_MATCH_TYPES = frozenset({"STANDARD"})


class ArenaV3FoundationOnly(NotImplementedError):
    """Raised for business operations intentionally deferred beyond Sprint 3."""


class ArenaV3ServiceError(ValueError):
    status_code = 400


class ArenaV3NotFound(ArenaV3ServiceError):
    status_code = 404


class ArenaV3Forbidden(ArenaV3ServiceError):
    status_code = 403


class ArenaV3Conflict(ArenaV3ServiceError):
    status_code = 409


class ArenaV3Unavailable(ArenaV3ServiceError):
    status_code = 503


class ArenaV3Service:
    def __init__(self, db: Session):
        self.db = db
        self.repository = ArenaV3Repository(db)

    @staticmethod
    def _fingerprint(payload) -> str:
        raw = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _money(stake: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        total = stake * Decimal("2")
        commission = total * MATCH_COMMISSION_PERCENT / Decimal("100")
        return total, commission, total - commission

    def _event(
        self,
        match: ArenaV3Match,
        *,
        event_type: str,
        actor_id: int,
        idempotency_key: str,
        from_status: ArenaV3Status | None,
    ) -> None:
        self.repository.add_event(ArenaV3MatchEvent(
            match_id=match.id,
            event_type=event_type,
            from_status=from_status.value if from_status else None,
            to_status=ArenaV3Status(match.status).value,
            actor_type="USER",
            actor_id=actor_id,
            idempotency_key=idempotency_key,
        ))

    def _locked_match(self, match_id: int) -> ArenaV3Match:
        match = self.repository.get_match_for_update(match_id)
        if match is None:
            raise ArenaV3NotFound("Arena V3 match not found")
        return match

    def _commit(self, match: ArenaV3Match) -> ArenaV3Match:
        try:
            self.db.commit()
            self.db.refresh(match)
            return match
        except IntegrityError as exc:
            self.db.rollback()
            raise ArenaV3Conflict("Arena V3 request conflicts with current state") from exc

    def create_match(self, *, payload, owner_id: int, idempotency_key: str):
        if not config.ARENA_V3_CREATE_ENABLED:
            raise ArenaV3Unavailable("Arena V3 create is disabled")
        fingerprint = self._fingerprint(payload)
        existing = self.repository.get_by_owner_idempotency(owner_id, idempotency_key)
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise ArenaV3Conflict("Idempotency key payload mismatch")
            return existing
        if self.repository.get_active_for_player(owner_id):
            raise ArenaV3Conflict("Player already has an active Arena V3 match")
        if payload.match_type not in SUPPORTED_MATCH_TYPES:
            raise ArenaV3ServiceError("Unsupported Arena V3 match type")

        stake = Decimal(payload.stake_efc)
        if stake <= 0 or stake.as_tuple().exponent < -2:
            raise ArenaV3ServiceError("Stake must be positive with at most two decimals")
        total, commission, reward = self._money(stake)
        match = self.repository.add_match(ArenaV3Match(
            public_id=f"ARV3{uuid4().hex[:20].upper()}",
            owner_id=owner_id,
            owner_efootball_username=payload.owner_efootball_username,
            stake_efc=stake,
            total_pool_efc=total,
            commission_efc=commission,
            winner_reward_efc=reward,
            match_type=payload.match_type,
            match_time_minutes=payload.match_time_minutes,
            extra_time_enabled=payload.extra_time_enabled,
            penalties_enabled=payload.penalties_enabled,
            status=ArenaV3Status.OPEN,
            settlement_status=ArenaV3SettlementStatus.NOT_STARTED,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        ))
        if config.ARENA_V3_SETTLEMENT_ENABLED:
            from app.services.arena_v3_settlement import lock_match_stake
            lock_match_stake(self.db, owner_id, stake, match.id)
        self._event(
            match, event_type="CREATE", actor_id=owner_id,
            idempotency_key=f"create:{idempotency_key}", from_status=None,
        )
        return self._commit(match)

    def join_match(self, *, match_id: int, payload, opponent_id: int, idempotency_key: str):
        match = self._locked_match(match_id)
        previous = self.repository.get_event_by_idempotency(
            match_id, f"join:{idempotency_key}"
        )
        if previous:
            if match.opponent_id != opponent_id:
                raise ArenaV3Conflict("Idempotency key belongs to another player")
            return match
        if match.owner_id == opponent_id:
            raise ArenaV3Conflict("Match creator cannot join own match")
        if match.status != ArenaV3Status.OPEN or match.opponent_id is not None:
            raise ArenaV3Conflict("Arena V3 match is not open")
        if self.repository.get_active_for_player(opponent_id):
            raise ArenaV3Conflict("Player already has an active Arena V3 match")
        if config.ARENA_V3_SETTLEMENT_ENABLED:
            from app.services.arena_v3_settlement import lock_match_stake
            lock_match_stake(
                self.db, opponent_id, match.stake_efc, match.id
            )

        from_status = ArenaV3Status(match.status)
        match.opponent_id = opponent_id
        match.opponent_efootball_username = payload.opponent_efootball_username
        transition_arena_v3(match, ArenaV3Status.READY)
        self._event(
            match, event_type="JOIN", actor_id=opponent_id,
            idempotency_key=f"join:{idempotency_key}", from_status=from_status,
        )
        return self._commit(match)

    def ready(self, *, match_id: int, player_id: int, payload=None):
        match = self._locked_match(match_id)
        if player_id not in {match.owner_id, match.opponent_id}:
            raise ArenaV3Forbidden("Player is not a match participant")
        already_ready = (
            match.owner_ready_at if player_id == match.owner_id
            else match.opponent_ready_at
        )
        if already_ready is not None and match.status in {
            ArenaV3Status.READY,
            ArenaV3Status.WAITING_ROOM_CODE,
        }:
            return match
        if match.status != ArenaV3Status.READY:
            raise ArenaV3Conflict("Arena V3 match is not in READY status")

        now = datetime.now(timezone.utc)
        if player_id == match.owner_id:
            match.owner_ready_at = now
            side = "owner"
        else:
            match.opponent_ready_at = now
            side = "opponent"

        from_status = ArenaV3Status(match.status)
        if match.owner_ready_at and match.opponent_ready_at:
            transition_arena_v3(match, ArenaV3Status.WAITING_ROOM_CODE)
        else:
            match.version += 1
        self._event(
            match, event_type="READY", actor_id=player_id,
            idempotency_key=f"ready:{side}", from_status=from_status,
        )
        return self._commit(match)

    def submit_room_code(self, *, match_id: int, owner_id: int, payload):
        match = self._locked_match(match_id)
        if match.owner_id != owner_id:
            raise ArenaV3Forbidden("Only match creator can submit room code")
        if match.status == ArenaV3Status.PLAYING and match.room_code == payload.room_code:
            return match
        if match.status != ArenaV3Status.WAITING_ROOM_CODE:
            raise ArenaV3Conflict("Arena V3 match is not waiting for room code")
        from_status = ArenaV3Status(match.status)
        now = datetime.now(timezone.utc)
        match.room_code = payload.room_code
        match.room_code_created_at = now
        match.playing_started_at = now
        match.screenshot_started_at = now + timedelta(
            minutes=match.match_time_minutes
        )
        match.screenshot_deadline_at = (
            match.screenshot_started_at
            + timedelta(seconds=SCREENSHOT_UPLOAD_WINDOW_SECONDS)
        )
        transition_arena_v3(match, ArenaV3Status.PLAYING)
        self._event(
            match, event_type="ROOM_CODE", actor_id=owner_id,
            idempotency_key="room-code", from_status=from_status,
        )
        return self._commit(match)

    def upload_screenshot(
        self,
        *,
        match_id: int,
        player_id: int,
        idempotency_key: str,
        storage_key: str,
        file_hash: str,
        mime_type: str,
        file_size: int,
        width: int,
        height: int,
        now: datetime | None = None,
    ):
        match = self._locked_match(match_id)
        if player_id not in {match.owner_id, match.opponent_id}:
            raise ArenaV3Forbidden("Player is not a match participant")
        if match.status != ArenaV3Status.WAITING_SCREENSHOT:
            raise ArenaV3Conflict("Arena V3 match is not accepting screenshots")
        now = now or datetime.now(timezone.utc)
        deadline = match.screenshot_deadline_at
        if deadline is None or deadline.replace(tzinfo=deadline.tzinfo or timezone.utc) <= now:
            raise ArenaV3Conflict("Screenshot upload window has expired")
        existing = self.repository.get_player_screenshot(match_id, player_id)
        if existing:
            raise ArenaV3Conflict("Player screenshot already uploaded")

        screenshot = self.repository.add_screenshot(ArenaV3MatchScreenshot(
            match_id=match.id,
            player_id=player_id,
            storage_key=storage_key,
            file_hash=file_hash,
            mime_type=mime_type,
            file_size=file_size,
            width=width,
            height=height,
            validation_status=ArenaV3EvidenceStatus.PENDING,
            uploaded_at=now,
        ))
        self._event(
            match,
            event_type="SCREENSHOT_UPLOADED",
            actor_id=player_id,
            idempotency_key=f"screenshot:{idempotency_key}",
            from_status=ArenaV3Status.WAITING_SCREENSHOT,
        )
        try:
            self.db.commit()
            self.db.refresh(screenshot)
            return screenshot
        except IntegrityError as exc:
            self.db.rollback()
            raise ArenaV3Conflict("Duplicate screenshot upload") from exc

    def ensure_screenshot_upload_allowed(
        self, *, match_id: int, player_id: int, now: datetime | None = None
    ) -> None:
        match = self.repository.get_match(match_id)
        if match is None:
            raise ArenaV3NotFound("Arena V3 match not found")
        if player_id not in {match.owner_id, match.opponent_id}:
            raise ArenaV3Forbidden("Player is not a match participant")
        if match.status != ArenaV3Status.WAITING_SCREENSHOT:
            raise ArenaV3Conflict("Arena V3 match is not accepting screenshots")
        now = now or datetime.now(timezone.utc)
        deadline = match.screenshot_deadline_at
        if deadline is None or deadline.replace(tzinfo=deadline.tzinfo or timezone.utc) <= now:
            raise ArenaV3Conflict("Screenshot upload window has expired")
        if self.repository.get_player_screenshot(match_id, player_id):
            raise ArenaV3Conflict("Player screenshot already uploaded")

    def list_screenshots(self, *, match_id: int, player_id: int):
        match = self.repository.get_match(match_id)
        if match is None:
            raise ArenaV3NotFound("Arena V3 match not found")
        if player_id not in {match.owner_id, match.opponent_id}:
            raise ArenaV3Forbidden("Player is not a match participant")
        return self.repository.list_screenshots(match_id)

    def start_ai_review(self, *, match_id: int):
        if not config.ARENA_V3_AI_ENABLED:
            raise ArenaV3Unavailable("Arena V3 AI is disabled")
        from app.services.arena_v3_workers import start_ai_review
        return start_ai_review(self.db, match_id)

    def submit_appeal(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 appeal business logic is not enabled")

    def finish_match(self, *, match_id: int):
        from app.services.arena_v3_settlement import settle_completed_match
        return settle_completed_match(self.db, match_id)

    def cancel_match(
        self, *, match_id: int, player_id: int, payload, idempotency_key: str
    ):
        match = self._locked_match(match_id)
        previous = self.repository.get_event_by_idempotency(
            match_id, f"cancel:{idempotency_key}"
        )
        if previous:
            if previous.actor_id != player_id:
                raise ArenaV3Conflict("Idempotency key belongs to another player")
            return match
        if player_id not in {match.owner_id, match.opponent_id}:
            raise ArenaV3Forbidden("Player is not a match participant")
        if match.status not in {
            ArenaV3Status.OPEN,
            ArenaV3Status.READY,
            ArenaV3Status.WAITING_ROOM_CODE,
        }:
            raise ArenaV3Conflict("Arena V3 match cannot be cancelled in current status")
        from_status = ArenaV3Status(match.status)
        try:
            transition_arena_v3(match, ArenaV3Status.CANCELLED)
        except ArenaV3InvalidTransition as exc:
            raise ArenaV3Conflict(str(exc)) from exc
        match.cancel_reason = payload.reason_code
        self._event(
            match, event_type="CANCEL", actor_id=player_id,
            idempotency_key=f"cancel:{idempotency_key}", from_status=from_status,
        )
        if config.ARENA_V3_SETTLEMENT_ENABLED:
            from app.services.arena_v3_settlement import refund_match
            return refund_match(
                self.db, match.id, reason=payload.reason_code
            )
        return self._commit(match)

    def history(self, *, player_id: int, limit: int = 50, offset: int = 0):
        return self.repository.list_history(
            player_id, limit=limit, offset=offset
        )

    def profile(self, *, player_id: int):
        return self.repository.get_stats(player_id)

    def ranking(self, *args, **kwargs):
        raise ArenaV3FoundationOnly("Arena V3 ranking query is not enabled")
