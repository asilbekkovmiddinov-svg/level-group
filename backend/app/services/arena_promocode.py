from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.arena_promocode import (
    ArenaTicketPromocode,
    ArenaTicketPromocodeClaim,
)
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet, TicketKind
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3NotFound


def _utc_now():
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_code(value: str) -> str:
    return "".join(value.strip().upper().split())


class ArenaPromocodeService:
    def __init__(self, db):
        self.db = db

    def claim(self, telegram_id: int, raw_code: str) -> dict:
        code = normalize_code(raw_code)
        if not code or len(code) > 32:
            raise ArenaV3NotFound("Promokod topilmadi")

        user = self.db.execute(
            select(User).where(User.telegram_id == telegram_id).with_for_update()
        ).scalar_one_or_none()
        if user is None:
            raise ArenaV3NotFound("Foydalanuvchi topilmadi")

        promo = self.db.execute(
            select(ArenaTicketPromocode)
            .where(ArenaTicketPromocode.code == code)
            .with_for_update()
        ).scalar_one_or_none()
        if promo is None or not promo.is_active:
            raise ArenaV3NotFound("Promokod topilmadi yoki faol emas")

        now = _utc_now()
        if promo.expires_at is not None and _as_utc(promo.expires_at) <= now:
            raise ArenaV3Conflict("Promokod muddati tugagan")
        if promo.usage_limit is not None and promo.usage_count >= promo.usage_limit:
            raise ArenaV3Conflict("Promokod limiti tugagan")

        existing = self.db.execute(
            select(ArenaTicketPromocodeClaim).where(
                ArenaTicketPromocodeClaim.promocode_id == promo.id,
                ArenaTicketPromocodeClaim.telegram_id == telegram_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ArenaV3Conflict("Bu promokoddan avval foydalangansiz")

        wallet = self.db.execute(
            select(GameTicketWallet)
            .where(GameTicketWallet.telegram_id == telegram_id)
            .with_for_update()
        ).scalar_one_or_none()
        if wallet is None:
            wallet = GameTicketWallet(telegram_id=telegram_id)
            self.db.add(wallet)
            self.db.flush()

        claim = ArenaTicketPromocodeClaim(
            promocode_id=promo.id,
            telegram_id=telegram_id,
            ticket_amount=promo.ticket_amount,
        )
        self.db.add(claim)
        wallet.tournament_tickets = (
            int(wallet.tournament_tickets or 0) + promo.ticket_amount
        )
        promo.usage_count += 1
        self.db.add(
            GameTicketLedger(
                id=str(uuid4()),
                telegram_id=telegram_id,
                ticket_kind=TicketKind.TOURNAMENT,
                operation="PROMOCODE_REWARD",
                amount=promo.ticket_amount,
                idempotency_key=f"arena-promocode:{promo.id}:{telegram_id}",
                metadata_json={"promocode": promo.code, "promocode_id": promo.id},
            )
        )
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ArenaV3Conflict("Bu promokoddan avval foydalangansiz") from exc

        return {
            "code": promo.code,
            "ticket_amount": promo.ticket_amount,
            "ticket_balance": int(wallet.tournament_tickets or 0),
        }
