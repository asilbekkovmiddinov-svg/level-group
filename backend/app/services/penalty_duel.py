from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from app.models.penalty_duel import (
    PenaltyDuelMatch,
    PenaltyDuelMode,
    PenaltyDuelRound,
    PenaltyDuelStatus,
    PenaltyDuelSubmission,
)
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, TicketKind
from app.services.wall_rush import get_wallet

REGULATION_ROUNDS = 5
ROUND_SECONDS = 30
VALID_DIRECTIONS = {
    "top-left",
    "top-right",
    "center",
    "bottom-left",
    "bottom-right",
}


class PenaltyDuelError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _value(item):
    return item.value if hasattr(item, "value") else item


def _display_name(user) -> str | None:
    if user is None:
        return None
    name = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
    return name or user.username or str(user.telegram_id)


def _is_player_one(match: PenaltyDuelMatch, telegram_id: int) -> bool:
    if telegram_id not in (match.player_one_id, match.player_two_id):
        raise PenaltyDuelError("Player is not a match participant")
    return telegram_id == match.player_one_id


def _round_history(db: Session, match: PenaltyDuelMatch, player_one: bool) -> list[dict]:
    rows = (
        db.query(PenaltyDuelRound)
        .filter(PenaltyDuelRound.match_id == match.id)
        .order_by(PenaltyDuelRound.round_number)
        .all()
    )
    result = []
    for row in rows:
        if player_one:
            result.append({
                "round": row.round_number,
                "your_kick": row.player_one_kick,
                "your_keeper": row.player_one_keeper,
                "opponent_kick": row.player_two_kick,
                "opponent_keeper": row.player_two_keeper,
                "you_goal": row.player_one_goal,
                "opponent_goal": row.player_two_goal,
            })
        else:
            result.append({
                "round": row.round_number,
                "your_kick": row.player_two_kick,
                "your_keeper": row.player_two_keeper,
                "opponent_kick": row.player_one_kick,
                "opponent_keeper": row.player_one_keeper,
                "you_goal": row.player_two_goal,
                "opponent_goal": row.player_one_goal,
            })
    return result


def match_response(db: Session, match: PenaltyDuelMatch, telegram_id: int) -> dict:
    player_one = _is_player_one(match, telegram_id)
    current_submissions = (
        db.query(PenaltyDuelSubmission.player_id)
        .filter(
            PenaltyDuelSubmission.match_id == match.id,
            PenaltyDuelSubmission.round_number == match.round_number,
        )
        .all()
    )
    submitted_ids = {row[0] for row in current_submissions}
    opponent_id = match.player_two_id if player_one else match.player_one_id
    you = match.player_one if player_one else match.player_two
    opponent = match.player_two if player_one else match.player_one
    your_score = match.player_one_score if player_one else match.player_two_score
    opponent_score = match.player_two_score if player_one else match.player_one_score
    return {
        "id": match.id,
        "mode": _value(match.mode),
        "status": _value(match.status),
        "side": "PLAYER_ONE" if player_one else "PLAYER_TWO",
        "you": {
            "telegram_id": telegram_id,
            "username": you.username if you else None,
            "display_name": _display_name(you),
        },
        "opponent": {
            "telegram_id": opponent_id,
            "username": opponent.username if opponent else None,
            "display_name": _display_name(opponent),
        } if opponent_id else None,
        "round_number": match.round_number,
        "regulation_rounds": REGULATION_ROUNDS,
        "sudden_death": match.round_number > REGULATION_ROUNDS,
        "your_score": your_score,
        "opponent_score": opponent_score,
        "you_submitted": telegram_id in submitted_ids,
        "opponent_submitted": opponent_id in submitted_ids if opponent_id else False,
        "round_deadline_at": (
            match.round_deadline_at.isoformat() if match.round_deadline_at else None
        ),
        "winner_id": match.winner_id,
        "reward_granted": bool(match.reward_granted),
        "history": _round_history(db, match, player_one),
        "version": match.version,
    }


def leaderboard_rows(
    db: Session,
    mode: PenaltyDuelMode,
    limit: int = 20,
) -> list[dict]:
    """Return a mode-specific rating calculated only from finished duels."""
    player_one_results = (
        db.query(
            PenaltyDuelMatch.player_one_id.label("telegram_id"),
            case(
                (PenaltyDuelMatch.winner_id == PenaltyDuelMatch.player_one_id, 1),
                else_=0,
            ).label("won"),
        )
        .filter(
            PenaltyDuelMatch.mode == mode,
            PenaltyDuelMatch.status == PenaltyDuelStatus.FINISHED,
            PenaltyDuelMatch.player_two_id.isnot(None),
            PenaltyDuelMatch.winner_id.isnot(None),
        )
    )
    player_two_results = (
        db.query(
            PenaltyDuelMatch.player_two_id.label("telegram_id"),
            case(
                (PenaltyDuelMatch.winner_id == PenaltyDuelMatch.player_two_id, 1),
                else_=0,
            ).label("won"),
        )
        .filter(
            PenaltyDuelMatch.mode == mode,
            PenaltyDuelMatch.status == PenaltyDuelStatus.FINISHED,
            PenaltyDuelMatch.player_two_id.isnot(None),
            PenaltyDuelMatch.winner_id.isnot(None),
        )
    )
    results = player_one_results.union_all(player_two_results).subquery()
    played = func.count(results.c.telegram_id)
    wins = func.sum(results.c.won)
    rating = 1000 + wins * 25
    rows = (
        db.query(
            User,
            played.label("played"),
            wins.label("wins"),
            rating.label("rating"),
        )
        .join(results, results.c.telegram_id == User.telegram_id)
        .group_by(User.telegram_id)
        .order_by(rating.desc(), wins.desc(), played.asc(), User.telegram_id.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "rank": rank,
            "telegram_id": user.telegram_id,
            "display_name": _display_name(user),
            "username": user.username,
            "played": int(games_played or 0),
            "wins": int(games_won or 0),
            "losses": int(games_played or 0) - int(games_won or 0),
            "rating": int(player_rating or 0),
        }
        for rank, (user, games_played, games_won, player_rating)
        in enumerate(rows, start=1)
    ]


def _ledger(
    db: Session,
    telegram_id: int,
    operation: str,
    amount: int,
    key: str,
    match_id: str,
    kind: TicketKind,
) -> None:
    if db.query(GameTicketLedger).filter_by(idempotency_key=key).first():
        return
    db.add(GameTicketLedger(
        id=str(uuid4()),
        telegram_id=telegram_id,
        ticket_kind=kind,
        operation=operation,
        amount=amount,
        match_id=None,
        idempotency_key=key,
        metadata_json={"penalty_duel_match_id": match_id},
    ))


def _spend_entry_tickets(db: Session, match: PenaltyDuelMatch) -> None:
    player_ids = sorted((match.player_one_id, match.player_two_id))
    for telegram_id in player_ids:
        wallet = get_wallet(db, telegram_id, lock=True)
        if wallet.game_tickets < 1:
            raise PenaltyDuelError("Both players need one Game Ticket")
    for telegram_id in player_ids:
        wallet = get_wallet(db, telegram_id, lock=True)
        wallet.game_tickets -= 1
        _ledger(
            db,
            telegram_id,
            "PENALTY_MATCH_SPEND",
            -1,
            f"penalty-duel:match:{match.id}:spend:{telegram_id}",
            match.id,
            TicketKind.GAME,
        )


def _refund_entry_tickets(db: Session, match: PenaltyDuelMatch) -> None:
    if match.mode != PenaltyDuelMode.TICKET or match.player_two_id is None:
        return
    for telegram_id in sorted((match.player_one_id, match.player_two_id)):
        key = f"penalty-duel:match:{match.id}:refund:{telegram_id}"
        if db.query(GameTicketLedger).filter_by(idempotency_key=key).first():
            continue
        get_wallet(db, telegram_id, lock=True).game_tickets += 1
        _ledger(
            db,
            telegram_id,
            "PENALTY_MATCH_REFUND",
            1,
            key,
            match.id,
            TicketKind.GAME,
        )


def _finish(db: Session, match: PenaltyDuelMatch, winner_id: int) -> None:
    match.status = PenaltyDuelStatus.FINISHED
    match.winner_id = winner_id
    match.finished_at = utc_now()
    match.round_deadline_at = None
    if match.mode == PenaltyDuelMode.TICKET and not match.reward_granted:
        key = f"penalty-duel:match:{match.id}:winner"
        if not db.query(GameTicketLedger).filter_by(idempotency_key=key).first():
            get_wallet(db, winner_id, lock=True).tournament_tickets += 1
            _ledger(
                db,
                winner_id,
                "PENALTY_WIN_REWARD",
                1,
                key,
                match.id,
                TicketKind.TOURNAMENT,
            )
        match.reward_granted = True


def join_match(
    db: Session,
    telegram_id: int,
    mode: PenaltyDuelMode,
) -> PenaltyDuelMatch:
    active = (
        db.query(PenaltyDuelMatch)
        .filter(
            PenaltyDuelMatch.status.in_((PenaltyDuelStatus.WAITING, PenaltyDuelStatus.ACTIVE)),
            or_(
                PenaltyDuelMatch.player_one_id == telegram_id,
                PenaltyDuelMatch.player_two_id == telegram_id,
            ),
        )
        .order_by(PenaltyDuelMatch.created_at.desc())
        .first()
    )
    if active:
        deadline = active.round_deadline_at
        if deadline and deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if (
            active.status == PenaltyDuelStatus.ACTIVE
            and deadline is not None
            and utc_now() > deadline
        ):
            process_timeout(db, active.id, telegram_id)
            active = None
        else:
            return active

    if mode == PenaltyDuelMode.TICKET:
        if get_wallet(db, telegram_id, lock=True).game_tickets < 1:
            raise PenaltyDuelError("One Game Ticket is required")

    waiting = (
        db.query(PenaltyDuelMatch)
        .filter(
            PenaltyDuelMatch.mode == mode,
            PenaltyDuelMatch.status == PenaltyDuelStatus.WAITING,
            PenaltyDuelMatch.player_one_id != telegram_id,
        )
        .order_by(PenaltyDuelMatch.created_at)
        .with_for_update(skip_locked=True)
        .first()
    )
    if waiting is None:
        match = PenaltyDuelMatch(
            id=str(uuid4()),
            mode=mode,
            status=PenaltyDuelStatus.WAITING,
            player_one_id=telegram_id,
        )
        db.add(match)
        db.commit()
        db.refresh(match)
        return match

    waiting.player_two_id = telegram_id
    if mode == PenaltyDuelMode.TICKET:
        _spend_entry_tickets(db, waiting)
    now = utc_now()
    waiting.status = PenaltyDuelStatus.ACTIVE
    waiting.started_at = now
    waiting.round_deadline_at = now + timedelta(seconds=ROUND_SECONDS)
    waiting.version += 1
    db.commit()
    db.refresh(waiting)
    return waiting


def get_active_match(db: Session, telegram_id: int) -> PenaltyDuelMatch | None:
    return (
        db.query(PenaltyDuelMatch)
        .filter(
            PenaltyDuelMatch.status.in_((PenaltyDuelStatus.WAITING, PenaltyDuelStatus.ACTIVE)),
            or_(
                PenaltyDuelMatch.player_one_id == telegram_id,
                PenaltyDuelMatch.player_two_id == telegram_id,
            ),
        )
        .order_by(PenaltyDuelMatch.created_at.desc())
        .first()
    )


def get_current_match(db: Session, telegram_id: int) -> PenaltyDuelMatch | None:
    active = get_active_match(db, telegram_id)
    if active:
        return active
    return (
        db.query(PenaltyDuelMatch)
        .filter(
            PenaltyDuelMatch.status == PenaltyDuelStatus.FINISHED,
            or_(
                PenaltyDuelMatch.player_one_id == telegram_id,
                PenaltyDuelMatch.player_two_id == telegram_id,
            ),
        )
        .order_by(PenaltyDuelMatch.finished_at.desc())
        .first()
    )


def cancel_waiting_match(
    db: Session,
    match_id: str,
    telegram_id: int,
) -> PenaltyDuelMatch:
    match = db.query(PenaltyDuelMatch).filter_by(id=match_id).with_for_update().first()
    if match is None or match.player_one_id != telegram_id:
        raise PenaltyDuelError("Match not found")
    if match.status != PenaltyDuelStatus.WAITING or match.player_two_id is not None:
        raise PenaltyDuelError("Only a waiting match can be cancelled")
    match.status = PenaltyDuelStatus.CANCELLED
    match.cancel_reason = "PLAYER_LEFT_QUEUE"
    match.finished_at = utc_now()
    match.version += 1
    db.commit()
    db.refresh(match)
    return match


def _resolve_round(db: Session, match: PenaltyDuelMatch) -> bool:
    submissions = (
        db.query(PenaltyDuelSubmission)
        .filter(
            PenaltyDuelSubmission.match_id == match.id,
            PenaltyDuelSubmission.round_number == match.round_number,
        )
        .order_by(PenaltyDuelSubmission.created_at)
        .all()
    )
    if len(submissions) < 2:
        return False
    by_player = {item.player_id: item for item in submissions}
    player_one = by_player[match.player_one_id]
    player_two = by_player[match.player_two_id]
    player_one_goal = player_one.kick_direction != player_two.keeper_direction
    player_two_goal = player_two.kick_direction != player_one.keeper_direction
    db.add(PenaltyDuelRound(
        id=str(uuid4()),
        match_id=match.id,
        round_number=match.round_number,
        player_one_kick=player_one.kick_direction,
        player_one_keeper=player_one.keeper_direction,
        player_two_kick=player_two.kick_direction,
        player_two_keeper=player_two.keeper_direction,
        player_one_goal=player_one_goal,
        player_two_goal=player_two_goal,
    ))
    if player_one_goal:
        match.player_one_score += 1
    if player_two_goal:
        match.player_two_score += 1

    completed_round = match.round_number
    score_is_decided = match.player_one_score != match.player_two_score
    if completed_round >= REGULATION_ROUNDS and score_is_decided:
        winner_id = (
            match.player_one_id
            if match.player_one_score > match.player_two_score
            else match.player_two_id
        )
        _finish(db, match, winner_id)
    else:
        match.round_number += 1
        match.round_deadline_at = utc_now() + timedelta(seconds=ROUND_SECONDS)
    return True


def submit_choices(
    db: Session,
    match_id: str,
    telegram_id: int,
    kick_direction: str,
    keeper_direction: str,
    expected_version: int,
    idempotency_key: str,
) -> PenaltyDuelMatch:
    if kick_direction not in VALID_DIRECTIONS or keeper_direction not in VALID_DIRECTIONS:
        raise PenaltyDuelError("Invalid penalty direction")
    match = db.query(PenaltyDuelMatch).filter_by(id=match_id).with_for_update().first()
    if match is None:
        raise PenaltyDuelError("Match not found")
    _is_player_one(match, telegram_id)
    duplicate = (
        db.query(PenaltyDuelSubmission)
        .filter(PenaltyDuelSubmission.idempotency_key == idempotency_key)
        .first()
    )
    if duplicate:
        if duplicate.match_id != match.id or duplicate.player_id != telegram_id:
            raise PenaltyDuelError("Idempotency key is already used")
        return match
    if match.status != PenaltyDuelStatus.ACTIVE:
        raise PenaltyDuelError("Match is not active")
    if match.version != expected_version:
        raise PenaltyDuelError("Match version is stale")
    deadline = match.round_deadline_at
    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline and utc_now() > deadline:
        raise PenaltyDuelError("Round deadline has passed")
    existing = (
        db.query(PenaltyDuelSubmission)
        .filter_by(
            match_id=match.id,
            round_number=match.round_number,
            player_id=telegram_id,
        )
        .first()
    )
    if existing:
        raise PenaltyDuelError("Choices are already submitted for this round")
    db.add(PenaltyDuelSubmission(
        id=str(uuid4()),
        match_id=match.id,
        round_number=match.round_number,
        player_id=telegram_id,
        kick_direction=kick_direction,
        keeper_direction=keeper_direction,
        idempotency_key=idempotency_key,
    ))
    db.flush()
    _resolve_round(db, match)
    match.version += 1
    db.commit()
    db.refresh(match)
    return match


def process_timeout(
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
    submissions = (
        db.query(PenaltyDuelSubmission)
        .filter_by(match_id=match.id, round_number=match.round_number)
        .all()
    )
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
