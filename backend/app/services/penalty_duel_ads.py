from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.wall_rush import (
    PENALTY_DUEL_AD_PROVIDERS, GameTicketLedger, GameTicketWallet, TicketKind,
)
from app.services.wall_rush import get_wallet


PENALTY_DUEL_AD_COOLDOWN = timedelta(minutes=5)


class PenaltyDuelAdError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def grant_penalty_duel_ad_ticket(
    db: Session,
    telegram_id: int,
    provider: str,
    provider_event_id: str,
    *,
    now: datetime | None = None,
    commit: bool = True,
) -> GameTicketWallet:
    """Grant one Game Ticket after a trusted provider callback is verified."""
    normalized_provider = str(provider).strip().upper()
    if normalized_provider not in PENALTY_DUEL_AD_PROVIDERS:
        raise PenaltyDuelAdError("Unknown Penalty Duel ad provider")

    now = now or utc_now()
    key = f"penalty-duel:ad:{normalized_provider.lower()}:{provider_event_id}"
    duplicate = db.query(GameTicketLedger).filter_by(idempotency_key=key).first()
    if duplicate:
        return get_wallet(db, telegram_id)

    wallet = get_wallet(db, telegram_id, lock=True)
    last = wallet.last_penalty_duel_rewarded_ad_at
    if last is not None and _as_utc(now) < _as_utc(last) + PENALTY_DUEL_AD_COOLDOWN:
        raise PenaltyDuelAdError("Penalty Duel ad is available once per 5 minutes")

    wallet.game_tickets += 1
    wallet.last_penalty_duel_rewarded_ad_at = now
    wallet.penalty_duel_rewarded_ad_provider_index = (
        PENALTY_DUEL_AD_PROVIDERS.index(normalized_provider) + 1
    ) % len(PENALTY_DUEL_AD_PROVIDERS)
    db.add(GameTicketLedger(
        id=str(uuid4()),
        telegram_id=telegram_id,
        ticket_kind=TicketKind.GAME,
        operation="PENALTY_AD_GRANT",
        amount=1,
        match_id=None,
        idempotency_key=key,
        metadata_json={"provider": normalized_provider},
    ))
    if commit:
        db.commit()
        db.refresh(wallet)
    else:
        db.flush()
    return wallet
