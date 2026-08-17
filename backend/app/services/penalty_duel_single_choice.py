from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.penalty_duel import (
    PenaltyDuelMatch,
    PenaltyDuelRound,
    PenaltyDuelStatus,
    PenaltyDuelSubmission,
)
from app.services.penalty_duel import (
    ROUND_SECONDS,
    VALID_DIRECTIONS,
    PenaltyDuelError,
    _finish,
    _refund_entry_tickets,
    _is_player_one,
    utc_now,
)

REGULATION_SHOTS = 10


def player_role(match: PenaltyDuelMatch, telegram_id: int) -> str:
    """Return the only action this player may submit for the current shot."""
    is_one = _is_player_one(match, telegram_id)
    player_one_attacks = match.round_number % 2 == 1
    attacking = player_one_attacks if is_one else not player_one_attacks
    return "KICK" if attacking else "KEEPER"


def _resolve_shot(db: Session, match: PenaltyDuelMatch) -> bool:
    submissions = (
        db.query(PenaltyDuelSubmission)
        .filter(
            PenaltyDuelSubmission.match_id == match.id,
            PenaltyDuelSubmission.round_number == match.round_number,
        )
        .all()
    )
    if len(submissions) < 2:
        return False

    by_player = {item.player_id: item for item in submissions}
    player_one = by_player.get(match.player_one_id)
    player_two = by_player.get(match.player_two_id)
    if player_one is None or player_two is None:
        return False

    player_one_attacks = match.round_number % 2 == 1
    attacker = player_one if player_one_attacks else player_two
    defender = player_two if player_one_attacks else player_one
    goal = attacker.kick_direction != defender.keeper_direction

    db.add(PenaltyDuelRound(
        id=str(uuid4()),
        match_id=match.id,
        round_number=match.round_number,
        player_one_kick=player_one.kick_direction,
        player_one_keeper=player_one.keeper_direction,
        player_two_kick=player_two.kick_direction,
        player_two_keeper=player_two.keeper_direction,
        player_one_goal=bool(goal and player_one_attacks),
        player_two_goal=bool(goal and not player_one_attacks),
    ))

    if goal:
        if player_one_attacks:
            match.player_one_score += 1
        else:
            match.player_two_score += 1

    completed_shot = match.round_number
    completed_pair = completed_shot % 2 == 0
    regulation_done = completed_shot >= REGULATION_SHOTS
    score_decided = match.player_one_score != match.player_two_score

    if regulation_done and completed_pair and score_decided:
        winner_id = match.player_one_id if match.player_one_score > match.player_two_score else match.player_two_id
        _finish(db, match, winner_id)
    else:
        match.round_number += 1
        match.round_deadline_at = utc_now() + timedelta(seconds=ROUND_SECONDS)
    return True


def _prime_ai_for_current_shot(db: Session, match: PenaltyDuelMatch) -> None:
    from app.services.penalty_duel_ai import add_ai_submission, is_ai_player
    if is_ai_player(match.player_two_id) and match.status == PenaltyDuelStatus.ACTIVE:
        add_ai_submission(db, match)


def submit_single_choice(
    db: Session,
    match_id: str,
    telegram_id: int,
    direction: str,
    idempotency_key: str,
) -> PenaltyDuelMatch:
    if direction not in VALID_DIRECTIONS:
        raise PenaltyDuelError("Invalid penalty direction")

    match = db.query(PenaltyDuelMatch).filter_by(id=match_id).with_for_update().first()
    if match is None:
        raise PenaltyDuelError("Match not found")
    _is_player_one(match, telegram_id)

    duplicate = db.query(PenaltyDuelSubmission).filter(PenaltyDuelSubmission.idempotency_key == idempotency_key).first()
    if duplicate:
        if duplicate.match_id != match.id or duplicate.player_id != telegram_id:
            raise PenaltyDuelError("Idempotency key is already used")
        return match

    if match.status != PenaltyDuelStatus.ACTIVE:
        raise PenaltyDuelError("Match is not active")

    deadline = match.round_deadline_at
    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline and utc_now() > deadline:
        raise PenaltyDuelError("Round deadline has passed")

    existing = db.query(PenaltyDuelSubmission).filter_by(
        match_id=match.id,
        round_number=match.round_number,
        player_id=telegram_id,
    ).first()
    if existing:
        return match

    db.add(PenaltyDuelSubmission(
        id=str(uuid4()),
        match_id=match.id,
        round_number=match.round_number,
        player_id=telegram_id,
        kick_direction=direction,
        keeper_direction=direction,
        idempotency_key=idempotency_key,
    ))
    db.flush()
    _prime_ai_for_current_shot(db, match)
    resolved = _resolve_shot(db, match)
    if resolved:
        _prime_ai_for_current_shot(db, match)
    match.version += 1
    db.commit()
    db.refresh(match)
    return match


def process_single_choice_timeout(
    db: Session,
    match_id: str,
    telegram_id: int,
    now: datetime | None = None,
) -> PenaltyDuelMatch:
    match = db.query(PenaltyDuelMatch).filter_by(id=match_id).with_for_update().first()
    if match is None or telegram_id not in (match.player_one_id, match.player_two_id):
        raise PenaltyDuelError("Match not found")
    if match.status != PenaltyDuelStatus.ACTIVE:
        return match

    deadline = match.round_deadline_at
    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    current_time = now or utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    if deadline is None or current_time <= deadline:
        raise PenaltyDuelError("Round is still active")

    submissions = db.query(PenaltyDuelSubmission).filter_by(
        match_id=match.id,
        round_number=match.round_number,
    ).all()
    if not submissions:
        _refund_entry_tickets(db, match)
        match.status = PenaltyDuelStatus.CANCELLED
        match.cancel_reason = "ROUND_NO_RESPONSE"
        match.finished_at = utc_now()
        match.round_deadline_at = None
    elif len(submissions) == 1:
        _finish(db, match, submissions[0].player_id)

    match.version += 1
    db.commit()
    db.refresh(match)
    return match
