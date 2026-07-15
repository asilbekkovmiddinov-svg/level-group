from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func

from app.crud import match as match_crud
from app.crud.wallet import get_wallet_for_update
from app.models.match import Match, MatchResultType, MatchStatus
from app.services.arena_time import utc_now


TEST_TELEGRAM_ID = 1678146043

CLEANUP_STATUSES = (
    MatchStatus.WAITING_PLAYER,
    MatchStatus.WAITING_READY,
    MatchStatus.ROOM_READY,
    MatchStatus.ROOM_CREATED,
    MatchStatus.PLAYING,
    MatchStatus.WAITING_ADMIN,
    MatchStatus.TECHNICAL_REVIEW,
)

TERMINAL_STATUSES = (MatchStatus.COMPLETED, MatchStatus.CANCELLED)


@dataclass(frozen=True)
class CleanupTransition:
    match_id: int
    previous_status: str
    current_status: str


@dataclass(frozen=True)
class ArenaTestCleanupResult:
    telegram_id: int
    cleaned_count: int
    transitions: list[CleanupTransition]
    locked_efc: Decimal
    locked_efc_zero: bool
    new_match_allowed: bool


def _status_value(status) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _participant_filter(telegram_id: int):
    return (Match.creator_telegram_id == telegram_id) | (
        Match.opponent_telegram_id == telegram_id
    )


def _required_by_other_active_matches(db, telegram_id: int, excluded_match_id: int) -> Decimal:
    value = (
        db.query(func.coalesce(func.sum(Match.efc_amount), 0))
        .filter(_participant_filter(telegram_id))
        .filter(Match.id != excluded_match_id)
        .filter(Match.status.notin_(TERMINAL_STATUSES))
        .scalar()
    )
    return Decimal(str(value or 0))


def _release_attributable_lock(db, telegram_id: int, match: Match) -> Decimal:
    wallet = get_wallet_for_update(db, telegram_id)
    if not wallet:
        raise ValueError(f"Arena cleanup wallet not found: {telegram_id}")

    locked = Decimal(str(wallet.locked_efc or 0))
    required_elsewhere = _required_by_other_active_matches(db, telegram_id, match.id)
    releasable = min(
        Decimal(str(match.efc_amount)),
        max(Decimal("0"), locked - required_elsewhere),
    )
    if releasable > 0:
        match_crud._unlock_efc(
            db=db,
            telegram_id=telegram_id,
            amount=releasable,
            description=f"Arena test cleanup: match #{match.id}",
        )
    return releasable


def cleanup_test_matches(db) -> ArenaTestCleanupResult:
    match_ids = [
        row[0]
        for row in (
            db.query(Match.id)
            .filter(_participant_filter(TEST_TELEGRAM_ID))
            .filter(Match.status.in_(CLEANUP_STATUSES))
            .order_by(Match.id.asc())
            .all()
        )
    ]
    transitions = []

    for match_id in match_ids:
        try:
            match = (
                db.query(Match)
                .filter(Match.id == match_id)
                .with_for_update()
                .first()
            )
            if not match or match.status not in CLEANUP_STATUSES:
                db.rollback()
                continue
            if TEST_TELEGRAM_ID not in (
                match.creator_telegram_id,
                match.opponent_telegram_id,
            ):
                db.rollback()
                continue

            previous_status = _status_value(match.status)
            participants = sorted(
                {
                    participant
                    for participant in (
                        match.creator_telegram_id,
                        match.opponent_telegram_id,
                    )
                    if participant is not None
                }
            )
            for participant in participants:
                _release_attributable_lock(db, participant, match)

            now = utc_now()
            match.status = MatchStatus.CANCELLED
            match.result_type = MatchResultType.CANCELLED
            match.cancel_reason = "Authorized Arena test cleanup"
            match.resolved_at = now
            match.timeout_deadline_at = None
            match.updated_at = now
            db.commit()
            transitions.append(
                CleanupTransition(
                    match_id=match.id,
                    previous_status=previous_status,
                    current_status=MatchStatus.CANCELLED.value,
                )
            )
        except Exception:
            db.rollback()
            raise

    wallet = get_wallet_for_update(db, TEST_TELEGRAM_ID)
    if not wallet:
        db.rollback()
        raise ValueError("Arena cleanup wallet not found")
    locked_efc = Decimal(str(wallet.locked_efc or 0))
    active_count = (
        db.query(func.count(Match.id))
        .filter(_participant_filter(TEST_TELEGRAM_ID))
        .filter(Match.status.notin_(TERMINAL_STATUSES))
        .scalar()
        or 0
    )
    db.rollback()

    return ArenaTestCleanupResult(
        telegram_id=TEST_TELEGRAM_ID,
        cleaned_count=len(transitions),
        transitions=transitions,
        locked_efc=locked_efc,
        locked_efc_zero=locked_efc == 0,
        new_match_allowed=active_count == 0,
    )

