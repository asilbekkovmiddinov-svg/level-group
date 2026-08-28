from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.wall_rush import GameTicketLedger, GameTicketWallet, TicketKind


COIN_ORDER_TICKET_BONUS_PERCENT = 10


@dataclass(frozen=True)
class CoinOrderTicketBonus:
    amount: int
    ticket_balance: int | None


def coin_order_ticket_bonus_amount(coins_amount: int) -> int:
    amount = max(0, int(coins_amount or 0))
    return amount * COIN_ORDER_TICKET_BONUS_PERCENT // 100


def award_coin_order_ticket_bonus(
    db: Session,
    order,
) -> CoinOrderTicketBonus:
    if str(getattr(order, "product_type", "")).upper() != "COIN":
        return CoinOrderTicketBonus(amount=0, ticket_balance=None)

    bonus = coin_order_ticket_bonus_amount(order.coins_amount)
    if bonus <= 0:
        return CoinOrderTicketBonus(amount=0, ticket_balance=None)

    idempotency_key = f"coin-order-ticket-bonus:{order.id}"
    existing = db.execute(
        select(GameTicketLedger).where(
            GameTicketLedger.idempotency_key == idempotency_key
        )
    ).scalar_one_or_none()

    wallet = db.execute(
        select(GameTicketWallet)
        .where(GameTicketWallet.telegram_id == order.telegram_id)
        .with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        return CoinOrderTicketBonus(
            amount=int(existing.amount),
            ticket_balance=(
                int(wallet.tournament_tickets or 0) if wallet is not None else None
            ),
        )

    if wallet is None:
        wallet = GameTicketWallet(telegram_id=order.telegram_id)
        db.add(wallet)
        db.flush()

    wallet.tournament_tickets = int(wallet.tournament_tickets or 0) + bonus
    db.add(GameTicketLedger(
        id=str(uuid4()),
        telegram_id=order.telegram_id,
        ticket_kind=TicketKind.TOURNAMENT,
        operation="COIN_ORDER_BONUS",
        amount=bonus,
        idempotency_key=idempotency_key,
        metadata_json={
            "order_id": order.id,
            "coin_amount": int(order.coins_amount or 0),
            "bonus_percent": COIN_ORDER_TICKET_BONUS_PERCENT,
        },
    ))
    return CoinOrderTicketBonus(
        amount=bonus,
        ticket_balance=int(wallet.tournament_tickets),
    )
