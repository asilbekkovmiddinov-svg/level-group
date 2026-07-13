from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.match import Match, MatchGameType, MatchResultType, MatchStats, MatchStatus
from app.models.wallet import Wallet
from app.models.transaction import Transaction
from app.services.arena_state_machine import (
    ArenaAction,
    ensure_action_allowed,
    ensure_evidence_not_repeated,
    ensure_ready_not_repeated,
)


MATCH_COMMISSION_PERCENT = Decimal("5.00")
READY_WINDOW_MINUTES = 5
DEFAULT_MATCH_RATING = 1000


def _to_decimal(value) -> Decimal:
    return Decimal(str(value))


def _calculate_match_money(efc_amount: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    efc_amount = _to_decimal(efc_amount)
    total_pool = efc_amount * Decimal("2")
    commission_amount = total_pool * MATCH_COMMISSION_PERCENT / Decimal("100")
    winner_reward = total_pool - commission_amount
    return total_pool, commission_amount, winner_reward


def _get_wallet(db: Session, telegram_id: int) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.telegram_id == telegram_id).first()
    if not wallet:
        raise ValueError("Hamyon topilmadi")
    return wallet


def _lock_efc(db: Session, telegram_id: int, amount: Decimal, description: str) -> None:
    wallet = _get_wallet(db, telegram_id)
    amount = _to_decimal(amount)

    if _to_decimal(wallet.efc_balance) < amount:
        raise ValueError("EFC balans yetarli emas")

    balance_before = _to_decimal(wallet.efc_balance)

    wallet.efc_balance = _to_decimal(wallet.efc_balance) - amount
    wallet.locked_efc = _to_decimal(wallet.locked_efc) + amount

    transaction = Transaction(
        telegram_id=telegram_id,
        currency="EFC",
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.efc_balance,
        type="MATCH_LOCK",
        status="SUCCESS",
        description=description,
    )
    db.add(transaction)


def _unlock_efc(db: Session, telegram_id: int, amount: Decimal, description: str) -> None:
    wallet = _get_wallet(db, telegram_id)
    amount = _to_decimal(amount)

    if _to_decimal(wallet.locked_efc) < amount:
        raise ValueError("Locked EFC yetarli emas")

    balance_before = _to_decimal(wallet.efc_balance)

    wallet.locked_efc = _to_decimal(wallet.locked_efc) - amount
    wallet.efc_balance = _to_decimal(wallet.efc_balance) + amount

    transaction = Transaction(
        telegram_id=telegram_id,
        currency="EFC",
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.efc_balance,
        type="MATCH_UNLOCK",
        status="SUCCESS",
        description=description,
    )
    db.add(transaction)


def _take_locked_efc(db: Session, telegram_id: int, amount: Decimal, description: str) -> None:
    wallet = _get_wallet(db, telegram_id)
    amount = _to_decimal(amount)

    if _to_decimal(wallet.locked_efc) < amount:
        raise ValueError("Locked EFC yetarli emas")

    balance_before = _to_decimal(wallet.efc_balance)

    wallet.locked_efc = _to_decimal(wallet.locked_efc) - amount

    transaction = Transaction(
        telegram_id=telegram_id,
        currency="EFC",
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.efc_balance,
        type="MATCH_SPEND",
        status="SUCCESS",
        description=description,
    )
    db.add(transaction)


def _add_efc(db: Session, telegram_id: int, amount: Decimal, description: str) -> None:
    wallet = _get_wallet(db, telegram_id)
    amount = _to_decimal(amount)

    balance_before = _to_decimal(wallet.efc_balance)

    wallet.efc_balance = _to_decimal(wallet.efc_balance) + amount

    transaction = Transaction(
        telegram_id=telegram_id,
        currency="EFC",
        amount=amount,
        balance_before=balance_before,
        balance_after=wallet.efc_balance,
        type="MATCH_REWARD",
        status="SUCCESS",
        description=description,
    )
    db.add(transaction)


def get_match(db: Session, match_id: int) -> Optional[Match]:
    return db.query(Match).filter(Match.id == match_id).first()


def get_match_for_update(db: Session, match_id: int) -> Optional[Match]:
    return (
        db.query(Match)
        .filter(Match.id == match_id)
        .with_for_update()
        .first()
    )


def is_match_participant(match: Match, telegram_id: int) -> bool:
    return telegram_id in (match.creator_telegram_id, match.opponent_telegram_id)


def get_open_matches(db: Session, skip: int = 0, limit: int = 20) -> list[Match]:
    return (
        db.query(Match)
        .filter(Match.status == MatchStatus.WAITING_PLAYER)
        .order_by(Match.scheduled_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_user_matches(
    db: Session,
    telegram_id: int,
    skip: int = 0,
    limit: int = 20,
) -> list[Match]:
    return (
        db.query(Match)
        .filter(
            (Match.creator_telegram_id == telegram_id)
            | (Match.opponent_telegram_id == telegram_id)
        )
        .order_by(Match.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_due_scheduled_matches(db: Session, limit: int = 50) -> list[Match]:
    now = datetime.utcnow() + timedelta(hours=5)
    ready_window_opens_at = now + timedelta(minutes=READY_WINDOW_MINUTES)

    return (
        db.query(Match)
        .filter(Match.status == MatchStatus.SCHEDULED)
        .filter(Match.ready_check_started_at.is_(None))
        .filter(Match.scheduled_at <= ready_window_opens_at)
        .order_by(Match.scheduled_at.asc())
        .limit(limit)
        .all()
    )


def get_expired_ready_matches(db: Session, limit: int = 50) -> list[Match]:
    now = datetime.utcnow()

    return (
        db.query(Match)
        .filter(Match.status == MatchStatus.READY_CHECK)
        .filter(Match.ready_check_started_at.is_not(None))
        .filter(Match.ready_check_deadline_at <= now)
        .order_by(Match.ready_check_deadline_at.asc())
        .limit(limit)
        .all()
    )


def create_match(
    db: Session,
    creator_telegram_id: int,
    efc_amount: Decimal,
    scheduled_at: datetime,
    game_type: MatchGameType = MatchGameType.EFOOTBALL,
    rules_accepted: bool = False,
) -> Match:
    efc_amount = _to_decimal(efc_amount)

    if scheduled_at.tzinfo is not None:
        scheduled_at = scheduled_at.astimezone(timezone(timedelta(hours=5))).replace(tzinfo=None)

    now_uz = datetime.utcnow() + timedelta(hours=5)

    if efc_amount <= 0:
        raise ValueError("EFC miqdori 0 dan katta bo‘lishi kerak")

    if not rules_accepted:
        raise ValueError("Match qoidalarini qabul qilish majburiy")

    if scheduled_at <= now_uz:
        raise ValueError("Match vaqti hozirgi vaqtdan keyin bo‘lishi kerak")
    total_pool, commission_amount, winner_reward = _calculate_match_money(efc_amount)

    _lock_efc(
        db=db,
        telegram_id=creator_telegram_id,
        amount=efc_amount,
        description="1vs1 Arena e’lon yaratildi, EFC locked qilindi",
    )

    match = Match(
        creator_telegram_id=creator_telegram_id,
        efc_amount=efc_amount,
        total_pool=total_pool,
        commission_amount=commission_amount,
        winner_reward=winner_reward,
        game_type=game_type,
        status=MatchStatus.WAITING_PLAYER,
        scheduled_at=scheduled_at,
        creator_rules_accepted_at=datetime.now(timezone.utc),
    )

    db.add(match)
    db.commit()
    db.refresh(match)

    return match


def accept_match(
    db: Session,
    match_id: int,
    opponent_telegram_id: int,
    rules_accepted: bool = False,
) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    ensure_action_allowed(match, ArenaAction.ACCEPT)

    if match.creator_telegram_id == opponent_telegram_id:
        raise ValueError("O‘zingiz yaratgan matchni qabul qila olmaysiz")

    if not rules_accepted:
        raise ValueError("Match qoidalarini qabul qilish majburiy")

    if match.scheduled_at <= datetime.utcnow():
        raise ValueError("Match vaqti o‘tib ketgan")

    _lock_efc(
        db=db,
        telegram_id=opponent_telegram_id,
        amount=match.efc_amount,
        description="1vs1 Arena match qabul qilindi, EFC locked qilindi",
    )

    match.opponent_telegram_id = opponent_telegram_id
    match.opponent_rules_accepted_at = datetime.now(timezone.utc)
    match.status = MatchStatus.SCHEDULED
    match.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(match)

    return match


def start_ready_check(
    db: Session,
    match_id: int,
    now: Optional[datetime] = None,
) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    ensure_action_allowed(match, ArenaAction.START_READY_CHECK)

    now = now or datetime.utcnow()
    scheduled_at_utc = match.scheduled_at - timedelta(hours=5)
    window_opens_at = scheduled_at_utc - timedelta(minutes=READY_WINDOW_MINUTES)

    if now < window_opens_at:
        raise ValueError("Ready oynasi hali ochilmagan")

    match.status = MatchStatus.READY_CHECK
    match.ready_check_started_at = now
    match.ready_check_deadline_at = scheduled_at_utc
    match.ready_window_started_at = now.replace(tzinfo=timezone.utc)
    match.ready_deadline_at = scheduled_at_utc.replace(tzinfo=timezone.utc)
    match.updated_at = now

    db.commit()
    db.refresh(match)

    return match


def set_player_ready(db: Session, match_id: int, telegram_id: int) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    ensure_ready_not_repeated(match, telegram_id)

    now = datetime.utcnow()

    if match.ready_check_deadline_at and now > match.ready_check_deadline_at:
        raise ValueError("Ready vaqti tugagan")

    if telegram_id == match.creator_telegram_id:
        match.creator_ready = True
        match.creator_ready_at = now
    elif telegram_id == match.opponent_telegram_id:
        match.opponent_ready = True
        match.opponent_ready_at = now
    else:
        raise ValueError("Siz bu match ishtirokchisi emassiz")

    match.updated_at = now

    db.commit()
    db.refresh(match)

    return match


def finish_ready_check(
    db: Session,
    match_id: int,
    now: Optional[datetime] = None,
) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    ensure_action_allowed(match, ArenaAction.FINISH_READY_CHECK)

    now = now or datetime.utcnow()

    if match.ready_check_deadline_at and now < match.ready_check_deadline_at:
        raise ValueError("Ready check muddati hali tugamagan")

    if match.creator_ready and match.opponent_ready:
        match.status = MatchStatus.WAITING_ROOM_CODE
    elif match.creator_ready or match.opponent_ready:
        match.status = MatchStatus.TECHNICAL_WIN
    else:
        _unlock_efc(
            db=db,
            telegram_id=match.creator_telegram_id,
            amount=match.efc_amount,
            description="1vs1 Arena ready muddati tugadi, EFC unlock qilindi",
        )
        if match.opponent_telegram_id:
            _unlock_efc(
                db=db,
                telegram_id=match.opponent_telegram_id,
                amount=match.efc_amount,
                description="1vs1 Arena ready muddati tugadi, EFC unlock qilindi",
            )
        match.status = MatchStatus.CANCELLED
        match.result_type = MatchResultType.CANCELLED
        match.cancel_reason = "Ikkala foydalanuvchi ham ready bosmadi"
        match.resolved_at = now

    match.updated_at = now

    db.commit()
    db.refresh(match)

    return match


def create_room_code(
    db: Session,
    match_id: int,
    telegram_id: int,
    room_code: str,
) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    ensure_action_allowed(match, ArenaAction.CREATE_ROOM_CODE)

    if telegram_id != match.creator_telegram_id:
        raise ValueError("Faqat match yaratuvchisi Room Code kirita oladi")

    if match.room_code:
        raise ValueError("Room Code allaqachon yozilgan, uni o‘zgartirib bo‘lmaydi")

    clean_code = room_code.strip()

    if len(clean_code) < 3:
        raise ValueError("Room Code juda qisqa")

    if len(clean_code) > 64:
        raise ValueError("Room Code juda uzun")

    now = datetime.utcnow()

    match.room_code = clean_code
    match.room_code_created_by = telegram_id
    match.room_code_created_at = now
    match.status = MatchStatus.MATCH_STARTED
    match.updated_at = now

    db.commit()
    db.refresh(match)

    return match


def upload_result_screenshot(
    db: Session,
    match_id: int,
    telegram_id: int,
    screenshot_file_id: Optional[str] = None,
    video_file_id: Optional[str] = None,
) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    if telegram_id not in [match.creator_telegram_id, match.opponent_telegram_id]:
        raise ValueError("Siz bu match ishtirokchisi emassiz")

    if not screenshot_file_id and not video_file_id:
        raise ValueError("Screenshot yoki video file_id talab qilinadi")

    ensure_evidence_not_repeated(
        match,
        telegram_id,
        screenshot_submitted=bool(screenshot_file_id),
        video_submitted=bool(video_file_id),
    )

    now = datetime.utcnow()
    now_aware = datetime.now(timezone.utc)

    if telegram_id == match.creator_telegram_id:
        if screenshot_file_id:
            match.creator_result_screenshot = screenshot_file_id
            match.creator_result_uploaded_at = now
        if video_file_id:
            match.creator_result_video = video_file_id
            match.creator_result_video_uploaded_at = now_aware
    else:
        if screenshot_file_id:
            match.opponent_result_screenshot = screenshot_file_id
            match.opponent_result_uploaded_at = now
        if video_file_id:
            match.opponent_result_video = video_file_id
            match.opponent_result_video_uploaded_at = now_aware

    if match.creator_evidence_complete and match.opponent_evidence_complete:
        match.status = MatchStatus.WAITING_ADMIN
    match.updated_at = now

    db.commit()
    db.refresh(match)

    return match


def get_or_create_match_stats(db: Session, telegram_id: int) -> MatchStats:
    stats = db.query(MatchStats).filter(MatchStats.telegram_id == telegram_id).first()

    if stats:
        return stats

    stats = MatchStats(
        telegram_id=telegram_id,
        rating=DEFAULT_MATCH_RATING,
    )

    db.add(stats)
    db.flush()

    return stats


def _update_winner_stats(db: Session, telegram_id: int, reward: Decimal) -> None:
    stats = get_or_create_match_stats(db, telegram_id)
    reward = _to_decimal(reward)

    stats.total_matches += 1
    stats.wins += 1
    stats.win_streak += 1

    if stats.win_streak > stats.best_win_streak:
        stats.best_win_streak = stats.win_streak

    stats.total_efc_won = _to_decimal(stats.total_efc_won) + reward

    if reward > _to_decimal(stats.biggest_win):
        stats.biggest_win = reward

    if stats.total_matches > 0:
        stats.win_rate = Decimal(stats.wins) * Decimal("100") / Decimal(stats.total_matches)

    stats.rating += 25
    stats.updated_at = datetime.utcnow()


def _update_loser_stats(db: Session, telegram_id: int, lost_amount: Decimal) -> None:
    stats = get_or_create_match_stats(db, telegram_id)
    lost_amount = _to_decimal(lost_amount)

    stats.total_matches += 1
    stats.losses += 1
    stats.win_streak = 0
    stats.total_efc_lost = _to_decimal(stats.total_efc_lost) + lost_amount

    if stats.total_matches > 0:
        stats.win_rate = Decimal(stats.wins) * Decimal("100") / Decimal(stats.total_matches)

    stats.rating = max(0, stats.rating - 15)
    stats.updated_at = datetime.utcnow()


def resolve_match(
    db: Session,
    match_id: int,
    admin_telegram_id: int,
    winner_telegram_id: int,
    admin_comment: Optional[str] = None,
) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    ensure_action_allowed(match, ArenaAction.RESOLVE)

    if not match.opponent_telegram_id:
        raise ValueError("Matchda ikkinchi ishtirokchi yo‘q")

    players = [match.creator_telegram_id, match.opponent_telegram_id]

    if winner_telegram_id not in players:
        raise ValueError("G‘olib match ishtirokchisi bo‘lishi kerak")

    loser_telegram_id = (
        match.opponent_telegram_id
        if winner_telegram_id == match.creator_telegram_id
        else match.creator_telegram_id
    )

    _take_locked_efc(
        db=db,
        telegram_id=match.creator_telegram_id,
        amount=match.efc_amount,
        description="1vs1 Arena match yakunlandi",
    )
    _take_locked_efc(
        db=db,
        telegram_id=match.opponent_telegram_id,
        amount=match.efc_amount,
        description="1vs1 Arena match yakunlandi",
    )
    _add_efc(
        db=db,
        telegram_id=winner_telegram_id,
        amount=match.winner_reward,
        description="1vs1 Arena g‘olib mukofoti",
    )

    _update_winner_stats(db, winner_telegram_id, match.winner_reward)
    _update_loser_stats(db, loser_telegram_id, match.efc_amount)

    now = datetime.utcnow()

    match.winner_telegram_id = winner_telegram_id
    match.loser_telegram_id = loser_telegram_id
    match.result_type = (
        MatchResultType.TECHNICAL
        if match.status == MatchStatus.TECHNICAL_WIN
        else MatchResultType.NORMAL
    )
    match.admin_telegram_id = admin_telegram_id
    match.admin_comment = admin_comment
    match.status = MatchStatus.COMPLETED
    match.resolved_at = now
    match.updated_at = now

    db.commit()
    db.refresh(match)

    return match


def cancel_match(
    db: Session,
    match_id: int,
    cancel_reason: str,
    admin_telegram_id: Optional[int] = None,
) -> Match:
    match = get_match_for_update(db, match_id)

    if not match:
        raise ValueError("Match topilmadi")

    ensure_action_allowed(match, ArenaAction.CANCEL)

    _unlock_efc(
        db=db,
        telegram_id=match.creator_telegram_id,
        amount=match.efc_amount,
        description="1vs1 Arena match bekor qilindi",
    )

    if match.opponent_telegram_id:
        _unlock_efc(
            db=db,
            telegram_id=match.opponent_telegram_id,
            amount=match.efc_amount,
            description="1vs1 Arena match bekor qilindi",
        )

    now = datetime.utcnow()

    match.status = MatchStatus.CANCELLED
    match.result_type = MatchResultType.CANCELLED
    match.cancel_reason = cancel_reason
    match.admin_telegram_id = admin_telegram_id
    match.resolved_at = now
    match.updated_at = now

    db.commit()
    db.refresh(match)

    return match


def get_match_stats(db: Session, telegram_id: int) -> MatchStats:
    return get_or_create_match_stats(db, telegram_id)


def get_leaderboard(db: Session, period: str = "all", limit: int = 20) -> list[MatchStats]:
    return (
        db.query(MatchStats)
        .order_by(
            MatchStats.rating.desc(),
            MatchStats.wins.desc(),
            MatchStats.best_win_streak.desc(),
        )
        .limit(limit)
        .all()
    )


def get_match_guide() -> dict:
    return {
        "title": "1vs1 Arena qo‘llanma",
        "text": (
            "Match vaqtida online bo‘ling.\n"
            "“Men tayyorman” tugmasini bosing.\n"
            "Room Code chiqqach o‘yinni boshlang.\n"
            "O‘yin tugagach screenshot yuboring.\n"
            "Admin natijani tasdiqlaydi."
        ),
    }
