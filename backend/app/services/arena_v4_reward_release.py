import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import ARENA_V4_REWARD_RELEASE_INTERVAL_SECONDS
from app.crud.transaction import create_transaction
from app.crud.wallet import release_locked_reward_efc
from app.models.arena_v3 import (
    ArenaV3Match,
    ArenaV3MatchEvent,
    ArenaV4RewardHoldStatus,
    ArenaV4SettlementOperation,
    ArenaV4SettlementOperationStatus,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import ArenaV3Conflict


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RewardReleaseResult:
    match_id: int
    outcome: str


def _utc(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def release_match_reward(db, match_id: int, *, now=None) -> RewardReleaseResult:
    now = now or datetime.now(timezone.utc)
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        db.rollback()
        return RewardReleaseResult(match_id, "MISSING")
    if match.reward_hold_status == ArenaV4RewardHoldStatus.AVAILABLE:
        db.rollback()
        return RewardReleaseResult(match_id, "ALREADY_RELEASED")
    if (
        match.reward_hold_status != ArenaV4RewardHoldStatus.LOCKED
        or match.reward_release_at is None
        or _utc(match.reward_release_at) > now
    ):
        db.rollback()
        return RewardReleaseResult(match_id, "NOT_DUE")
    if match.has_appeal or repository.get_appeal_for_update(match.id) is not None:
        db.rollback()
        return RewardReleaseResult(match_id, "APPEAL_BLOCKED")
    credits = [
        item for item in repository.list_settlement_operations_for_update(
            match.id, match.result_version
        )
        if item.operation_type in {"REWARD_LOCK", "STAKE_REFUND"}
        and item.status == ArenaV4SettlementOperationStatus.COMPLETED
    ]
    if not credits:
        if match.winner_id is None:
            db.rollback()
            raise ArenaV3Conflict("Arena V4 locked reward ledger is missing")
        credits = [SimpleNamespace(
            player_id=match.winner_id,
            amount_efc=match.winner_reward_efc,
        )]
    released = {}
    for credit in credits:
        amount = Decimal(str(credit.amount_efc))
        wallet = release_locked_reward_efc(db, credit.player_id, amount)
        if wallet is None:
            db.rollback()
            raise ArenaV3Conflict("Arena V4 locked reward is unavailable")
        balance_after = Decimal(str(wallet.efc_balance))
        transaction = create_transaction(
            db=db,
            telegram_id=credit.player_id,
            currency="EFC",
            amount=amount,
            balance_before=balance_after - amount,
            balance_after=balance_after,
            type="ARENA_V4_REWARD_RELEASED",
            description=f"Arena V4 match #{match.id} reward released",
            commit=False,
        )
        repository.add_settlement_operation(ArenaV4SettlementOperation(
            match_id=match.id,
            result_version=match.result_version,
            player_id=credit.player_id,
            operation_type="REWARD_RELEASE",
            amount_efc=amount,
            status=ArenaV4SettlementOperationStatus.COMPLETED,
            wallet_transaction_id=transaction.id,
            idempotency_key=(
                f"arena-v4:{match.id}:{match.result_version}:"
                f"REWARD_RELEASE:{credit.player_id}"
            ),
            operation_metadata={"released_at": now.isoformat()},
            completed_at=now,
        ))
        released[credit.player_id] = str(amount)
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type="V4_REWARD_RELEASED",
        from_status=match.status.value,
        to_status=match.status.value,
        actor_type="SYSTEM",
        actor_id=None,
        idempotency_key=f"reward-release:{match.result_version}",
        event_metadata={"released": released},
    ))
    match.reward_hold_status = ArenaV4RewardHoldStatus.AVAILABLE
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ArenaV3Conflict("Arena V4 reward was already released") from exc
    return RewardReleaseResult(match.id, "RELEASED")


def run_reward_release_queue(db, *, limit=50, now=None):
    now = now or datetime.now(timezone.utc)
    match_ids = [
        row[0]
        for row in (
            db.query(ArenaV3Match.id)
            .filter(
                ArenaV3Match.reward_hold_status
                == ArenaV4RewardHoldStatus.LOCKED,
                ArenaV3Match.reward_release_at.is_not(None),
                ArenaV3Match.reward_release_at <= now,
                ArenaV3Match.has_appeal.is_(False),
            )
            .order_by(ArenaV3Match.reward_release_at, ArenaV3Match.id)
            .limit(limit)
            .all()
        )
    ]
    results = []
    for match_id in match_ids:
        try:
            results.append(release_match_reward(db, match_id, now=now))
        except (ArenaV3Conflict, SQLAlchemyError):
            db.rollback()
            logger.exception("arena_v4_reward_release_failed match_id=%s", match_id)
    return results


class ArenaV4RewardReleaseWorker:
    def __init__(
        self,
        session_factory,
        interval_seconds=ARENA_V4_REWARD_RELEASE_INTERVAL_SECONDS,
    ):
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="arena-v4-reward-release",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.interval_seconds + 1, 5))

    def _run(self):
        while not self._stop.is_set():
            db = self.session_factory()
            try:
                run_reward_release_queue(db)
            except Exception:
                db.rollback()
                logger.exception("arena_v4_reward_release_tick_failed")
            finally:
                db.close()
            self._stop.wait(self.interval_seconds)
