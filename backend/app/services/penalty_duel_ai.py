import random
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.penalty_duel import PenaltyDuelMatch, PenaltyDuelMode, PenaltyDuelStatus, PenaltyDuelSubmission
from app.models.user import User
from app.services.penalty_duel import ROUND_SECONDS, VALID_DIRECTIONS, _spend_entry_tickets, utc_now

AI_TELEGRAM_ID = -700000001
AI_FALLBACK_SECONDS = 10
AI_FIRST_NAME = "Player"


def is_ai_player(telegram_id: int | None) -> bool:
    return telegram_id == AI_TELEGRAM_ID


def ensure_ai_user(db: Session) -> User:
    user = db.query(User).filter(User.telegram_id == AI_TELEGRAM_ID).first()
    if user is None:
        user = User(
            telegram_id=AI_TELEGRAM_ID,
            first_name=AI_FIRST_NAME,
            username=None,
            language="uz",
            is_banned=False,
        )
        db.add(user)
        db.flush()
    return user


def waiting_for_ai(match: PenaltyDuelMatch) -> bool:
    if match.mode != PenaltyDuelMode.TICKET or match.status != PenaltyDuelStatus.WAITING:
        return False
    if match.player_two_id is not None or match.created_at is None:
        return False
    created = match.created_at
    now = utc_now()
    if created.tzinfo is None:
        created = created.replace(tzinfo=now.tzinfo)
    return now >= created + timedelta(seconds=AI_FALLBACK_SECONDS)


def activate_ai_opponent(db: Session, match: PenaltyDuelMatch) -> bool:
    """Attach the server AI only after the real-player matchmaking window expires."""
    if not waiting_for_ai(match):
        return False
    ensure_ai_user(db)
    match.player_two_id = AI_TELEGRAM_ID
    # Only the human pays the Ticket Match entry cost. The AI is a server actor.
    from app.services.wall_rush import get_wallet
    from app.models.wall_rush import GameTicketLedger, TicketKind
    from app.services.penalty_duel import _ledger

    human_wallet = get_wallet(db, match.player_one_id, lock=True)
    if human_wallet.game_tickets < 1:
        return False
    human_wallet.game_tickets -= 1
    _ledger(
        db,
        match.player_one_id,
        "PENALTY_MATCH_SPEND",
        -1,
        f"penalty-duel:match:{match.id}:spend:{match.player_one_id}",
        match.id,
        TicketKind.GAME,
    )
    now = utc_now()
    match.status = PenaltyDuelStatus.ACTIVE
    match.started_at = now
    match.round_deadline_at = now + timedelta(seconds=ROUND_SECONDS)
    match.version += 1
    db.flush()
    return True


def ai_direction() -> str:
    # Server-side randomness prevents the client from predicting or controlling AI actions.
    return random.SystemRandom().choice(tuple(VALID_DIRECTIONS))


def add_ai_submission(db: Session, match: PenaltyDuelMatch) -> PenaltyDuelSubmission | None:
    if not is_ai_player(match.player_two_id) or match.status != PenaltyDuelStatus.ACTIVE:
        return None
    existing = db.query(PenaltyDuelSubmission).filter_by(
        match_id=match.id,
        round_number=match.round_number,
        player_id=AI_TELEGRAM_ID,
    ).first()
    if existing:
        return existing
    direction = ai_direction()
    submission = PenaltyDuelSubmission(
        id=str(uuid4()),
        match_id=match.id,
        round_number=match.round_number,
        player_id=AI_TELEGRAM_ID,
        kick_direction=direction,
        keeper_direction=direction,
        idempotency_key=f"penalty-duel:ai:{match.id}:{match.round_number}",
    )
    db.add(submission)
    db.flush()
    return submission
