from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.domain.wall_rush import (
    GameState, InvalidAction, MoveAction, Orientation, Player, Wall, WallAction,
    apply_action,
)
from app.models.user import User
from app.models.wall_rush import (
    GameTicketLedger, GameTicketWallet, TicketKind, WallRushAction,
    WallRushActionType, WallRushMatch, WallRushMode, WallRushStatus,
)

TURN_SECONDS = 30
MAX_MISSED_TURNS = 3
WALL_RUSH_AD_COOLDOWN = timedelta(minutes=30)


class WallRushError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def match_response(match: WallRushMatch) -> dict:
    return {
        "id": match.id,
        "mode": _enum_value(match.mode),
        "status": _enum_value(match.status),
        "red_player_id": match.red_player_id,
        "blue_player_id": match.blue_player_id,
        "red_username": match.red_player.username if match.red_player else None,
        "blue_username": match.blue_player.username if match.blue_player else None,
        "red_display_name": (
            match.red_player.first_name or match.red_player.username
            if match.red_player else None
        ),
        "blue_display_name": (
            match.blue_player.first_name or match.blue_player.username
            if match.blue_player else None
        ),
        "current_turn_player_id": match.current_turn_player_id,
        "red": (match.red_row, match.red_column),
        "blue": (match.blue_row, match.blue_column),
        "walls": match.walls or [],
        "red_walls_remaining": match.red_walls_remaining,
        "blue_walls_remaining": match.blue_walls_remaining,
        "red_missed_turns": match.red_missed_turns,
        "blue_missed_turns": match.blue_missed_turns,
        "turn_number": match.turn_number,
        "turn_deadline_at": match.turn_deadline_at.isoformat() if match.turn_deadline_at else None,
        "winner_id": match.winner_id,
        "version": match.version,
    }



def leaderboard_rows(
    db: Session, mode: WallRushMode, limit: int = 20,
) -> list[dict]:
    """Return authoritative, mode-specific results from finished matches."""
    red_results = (
        db.query(
            WallRushMatch.red_player_id.label("telegram_id"),
            case(
                (WallRushMatch.winner_id == WallRushMatch.red_player_id, 1),
                else_=0,
            ).label("won"),
        )
        .filter(
            WallRushMatch.mode == mode,
            WallRushMatch.status == WallRushStatus.FINISHED,
            WallRushMatch.blue_player_id.isnot(None),
            WallRushMatch.winner_id.isnot(None),
        )
    )
    blue_results = (
        db.query(
            WallRushMatch.blue_player_id.label("telegram_id"),
            case(
                (WallRushMatch.winner_id == WallRushMatch.blue_player_id, 1),
                else_=0,
            ).label("won"),
        )
        .filter(
            WallRushMatch.mode == mode,
            WallRushMatch.status == WallRushStatus.FINISHED,
            WallRushMatch.blue_player_id.isnot(None),
            WallRushMatch.winner_id.isnot(None),
        )
    )
    results = red_results.union_all(blue_results).subquery()
    played = func.count(results.c.telegram_id)
    wins = func.sum(results.c.won)
    rows = (
        db.query(User, played.label("played"), wins.label("wins"))
        .join(results, results.c.telegram_id == User.telegram_id)
        .group_by(User.telegram_id)
        .order_by(wins.desc(), played.asc(), User.telegram_id.asc())
        .limit(limit)
        .all()
    )
    leaderboard = []
    for rank, (user, games_played, games_won) in enumerate(rows, start=1):
        display_name = " ".join(
            part for part in (user.first_name, user.last_name) if part
        ).strip()
        won = int(games_won or 0)
        total = int(games_played or 0)
        leaderboard.append({
            "rank": rank,
            "telegram_id": user.telegram_id,
            "display_name": display_name or user.username or str(user.telegram_id),
            "username": user.username,
            "played": total,
            "wins": won,
            "losses": total - won,
        })
    return leaderboard


def get_wallet(db: Session, telegram_id: int, lock: bool = False) -> GameTicketWallet:
    query = db.query(GameTicketWallet).filter(GameTicketWallet.telegram_id == telegram_id)
    if lock:
        query = query.with_for_update()
    wallet = query.first()
    if wallet is None:
        wallet = GameTicketWallet(telegram_id=telegram_id)
        db.add(wallet)
        db.flush()
    return wallet


def wallet_response(wallet: GameTicketWallet) -> dict:
    return {
        "game_tickets": wallet.game_tickets,
        "locked_game_tickets": wallet.locked_game_tickets,
        "tournament_tickets": wallet.tournament_tickets,
        "locked_tournament_tickets": wallet.locked_tournament_tickets,
        "last_rewarded_ad_at": wallet.last_rewarded_ad_at,
    }


def _ledger(
    db: Session, telegram_id: int, kind: TicketKind, operation: str,
    amount: int, key: str, match_id: str | None = None,
) -> None:
    db.add(GameTicketLedger(
        id=str(uuid4()), telegram_id=telegram_id, ticket_kind=kind,
        operation=operation, amount=amount, match_id=match_id,
        idempotency_key=key,
    ))


def grant_ad_ticket(
    db: Session, telegram_id: int, provider_event_id: str,
    now: datetime | None = None,
) -> GameTicketWallet:
    """Called only after a trusted ad provider callback has been verified."""
    now = now or utc_now()
    key = f"wall-rush:ad:{provider_event_id}"
    if db.query(GameTicketLedger).filter_by(idempotency_key=key).first():
        return get_wallet(db, telegram_id)
    wallet = get_wallet(db, telegram_id, lock=True)
    last = wallet.last_rewarded_ad_at
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now < last + WALL_RUSH_AD_COOLDOWN:
            raise WallRushError("Rewarded ad is available once per 30 minutes")
    wallet.game_tickets += 1
    wallet.last_rewarded_ad_at = now
    _ledger(db, telegram_id, TicketKind.GAME, "AD_GRANT", 1, key)
    db.commit()
    db.refresh(wallet)
    return wallet


def _spend_start_tickets(db: Session, match: WallRushMatch) -> None:
    for telegram_id in sorted((match.red_player_id, match.blue_player_id)):
        wallet = get_wallet(db, telegram_id, lock=True)
        if wallet.game_tickets < 1:
            raise WallRushError("Both players need one Game Ticket")
    for telegram_id in (match.red_player_id, match.blue_player_id):
        wallet = get_wallet(db, telegram_id, lock=True)
        wallet.game_tickets -= 1
        _ledger(
            db, telegram_id, TicketKind.GAME, "MATCH_SPEND", -1,
            f"wall-rush:match:{match.id}:spend:{telegram_id}", match.id,
        )


def join_match(db: Session, telegram_id: int, mode: WallRushMode) -> WallRushMatch:
    active = (
        db.query(WallRushMatch)
        .filter(
            WallRushMatch.status.in_((WallRushStatus.WAITING, WallRushStatus.ACTIVE)),
            ((WallRushMatch.red_player_id == telegram_id) | (WallRushMatch.blue_player_id == telegram_id)),
        )
        .order_by(WallRushMatch.created_at.desc())
        .first()
    )
    if active:
        return active

    if mode == WallRushMode.TICKET:
        wallet = get_wallet(db, telegram_id, lock=True)
        if wallet.game_tickets < 1:
            raise WallRushError("One Game Ticket is required")

    waiting = (
        db.query(WallRushMatch)
        .filter(
            WallRushMatch.mode == mode,
            WallRushMatch.status == WallRushStatus.WAITING,
            WallRushMatch.red_player_id != telegram_id,
        )
        .order_by(WallRushMatch.created_at)
        .with_for_update(skip_locked=True)
        .first()
    )
    if waiting is None:
        match = WallRushMatch(
            id=str(uuid4()), mode=mode, status=WallRushStatus.WAITING,
            red_player_id=telegram_id, walls=[],
        )
        db.add(match)
        db.commit()
        db.refresh(match)
        return match

    waiting.blue_player_id = telegram_id
    if mode == WallRushMode.TICKET:
        _spend_start_tickets(db, waiting)
    now = utc_now()
    waiting.status = WallRushStatus.ACTIVE
    waiting.current_turn_player_id = waiting.red_player_id
    waiting.started_at = now
    waiting.turn_deadline_at = now + timedelta(seconds=TURN_SECONDS)
    waiting.version += 1
    db.commit()
    db.refresh(waiting)
    return waiting


def get_active_match(db: Session, telegram_id: int) -> WallRushMatch | None:
    return (
        db.query(WallRushMatch)
        .filter(
            WallRushMatch.status.in_((WallRushStatus.WAITING, WallRushStatus.ACTIVE)),
            ((WallRushMatch.red_player_id == telegram_id) | (WallRushMatch.blue_player_id == telegram_id)),
        )
        .order_by(WallRushMatch.created_at.desc())
        .first()
    )


def _domain_state(match: WallRushMatch) -> GameState:
    player = Player.RED if match.current_turn_player_id == match.red_player_id else Player.BLUE
    walls = frozenset(
        Wall(item["row"], item["column"], Orientation(item["orientation"]))
        for item in (match.walls or [])
    )
    winner = None
    if match.winner_id == match.red_player_id:
        winner = Player.RED
    elif match.winner_id == match.blue_player_id:
        winner = Player.BLUE
    return GameState(
        red=(match.red_row, match.red_column),
        blue=(match.blue_row, match.blue_column),
        current_player=player,
        walls=walls,
        red_walls_remaining=match.red_walls_remaining,
        blue_walls_remaining=match.blue_walls_remaining,
        turn_number=match.turn_number,
        winner=winner,
    )


def _finish(db: Session, match: WallRushMatch, winner_id: int) -> None:
    match.status = WallRushStatus.FINISHED
    match.winner_id = winner_id
    match.finished_at = utc_now()
    match.turn_deadline_at = None
    if match.mode == WallRushMode.TICKET:
        wallet = get_wallet(db, winner_id, lock=True)
        wallet.tournament_tickets += 1
        _ledger(
            db, winner_id, TicketKind.TOURNAMENT, "WIN_REWARD", 1,
            f"wall-rush:match:{match.id}:winner", match.id,
        )


def submit_action(
    db: Session, match_id: str, telegram_id: int, action_type: str,
    row: int, column: int, orientation: str | None,
    expected_version: int, idempotency_key: str,
) -> WallRushMatch:
    match = db.query(WallRushMatch).filter_by(id=match_id).with_for_update().first()
    if match is None:
        raise WallRushError("Match not found")
    if telegram_id not in (match.red_player_id, match.blue_player_id):
        raise WallRushError("Player is not a match participant")
    duplicate = (
        db.query(WallRushAction)
        .filter_by(match_id=match_id, idempotency_key=idempotency_key)
        .first()
    )
    if duplicate:
        return match
    if match.status != WallRushStatus.ACTIVE:
        raise WallRushError("Match is not active")
    if match.current_turn_player_id != telegram_id:
        raise WallRushError("It is not this player's turn")
    if match.version != expected_version:
        raise WallRushError("Match version is stale")
    deadline = match.turn_deadline_at
    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline and utc_now() > deadline:
        raise WallRushError("Turn deadline has passed")

    state = _domain_state(match)
    wall_owners = {
        (
            item["row"],
            item["column"],
            item["orientation"],
        ): item.get("owner_id")
        for item in (match.walls or [])
    }
    try:
        if action_type == "MOVE":
            action = MoveAction((row, column))
            db_action = WallRushActionType.MOVE
            payload = {"row": row, "column": column}
        elif action_type == "WALL" and orientation:
            action = WallAction(Wall(row, column, Orientation(orientation)))
            db_action = WallRushActionType.WALL
            payload = {"row": row, "column": column, "orientation": orientation}
        else:
            raise WallRushError("Invalid action payload")
        updated = apply_action(state, action)
    except (InvalidAction, ValueError) as error:
        raise WallRushError(str(error)) from error

    match.red_row, match.red_column = updated.red
    match.blue_row, match.blue_column = updated.blue
    match.red_walls_remaining = updated.red_walls_remaining
    match.blue_walls_remaining = updated.blue_walls_remaining
    match.walls = [
        {
            "row": wall.row,
            "column": wall.column,
            "orientation": wall.orientation.value,
            "owner_id": wall_owners.get(
                (wall.row, wall.column, wall.orientation.value),
                telegram_id,
            ),
        }
        for wall in sorted(
            updated.walls,
            key=lambda item: (item.row, item.column, item.orientation.value),
        )
    ]
    match.turn_number = updated.turn_number
    match.current_turn_player_id = (
        match.red_player_id if updated.current_player is Player.RED else match.blue_player_id
    )
    match.turn_deadline_at = utc_now() + timedelta(seconds=TURN_SECONDS)
    match.version += 1
    db.add(WallRushAction(
        id=str(uuid4()), match_id=match.id, player_id=telegram_id,
        sequence=state.turn_number, action_type=db_action, payload=payload,
        idempotency_key=idempotency_key,
    ))
    if updated.winner is not None:
        _finish(db, match, telegram_id)
    db.commit()
    db.refresh(match)
    return match


def process_timeout(db: Session, match_id: str, telegram_id: int) -> WallRushMatch:
    match = db.query(WallRushMatch).filter_by(id=match_id).with_for_update().first()
    if match is None or telegram_id not in (match.red_player_id, match.blue_player_id):
        raise WallRushError("Match not found")
    if match.status != WallRushStatus.ACTIVE:
        return match
    deadline = match.turn_deadline_at
    if deadline and deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    if deadline is None or utc_now() <= deadline:
        raise WallRushError("Turn is still active")

    missed_id = match.current_turn_player_id
    if missed_id == match.red_player_id:
        match.red_missed_turns += 1
        misses = match.red_missed_turns
        winner_id = match.blue_player_id
    else:
        match.blue_missed_turns += 1
        misses = match.blue_missed_turns
        winner_id = match.red_player_id
    if misses >= MAX_MISSED_TURNS:
        _finish(db, match, winner_id)
    else:
        match.current_turn_player_id = winner_id
        match.turn_number += 1
        match.turn_deadline_at = utc_now() + timedelta(seconds=TURN_SECONDS)
    match.version += 1
    db.commit()
    db.refresh(match)
    return match


def cancel_waiting_match(
    db: Session, match_id: str, telegram_id: int,
) -> WallRushMatch:
    match = db.query(WallRushMatch).filter_by(id=match_id).with_for_update().first()
    if match is None or match.red_player_id != telegram_id:
        raise WallRushError("Match not found")
    if match.status != WallRushStatus.WAITING or match.blue_player_id is not None:
        raise WallRushError("Only a waiting match can be cancelled")
    match.status = WallRushStatus.CANCELLED
    match.cancel_reason = "PLAYER_LEFT_QUEUE"
    match.finished_at = utc_now()
    match.version += 1
    db.commit()
    db.refresh(match)
    return match
