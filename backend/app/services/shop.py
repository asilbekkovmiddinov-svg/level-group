from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import config
from app.models.shop import ShopPurchase, ShopSettings
from app.models.transaction import Transaction
from app.models.wallet import Wallet
from app.models.wall_rush import GameTicketLedger, GameTicketWallet, TicketKind


class ShopError(Exception):
    pass


class ShopNotFound(ShopError):
    pass


class ShopInvalidAmount(ShopError):
    pass


class ShopInsufficientBalance(ShopError):
    pass


class ShopIdempotencyConflict(ShopError):
    pass


class ShopOperationFailed(ShopError):
    pass


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def _result(db: Session, purchase: ShopPurchase) -> dict:
    wallet = db.get(Wallet, purchase.telegram_id)
    ticket_wallet = db.get(GameTicketWallet, purchase.telegram_id)
    return {
        "purchase_id": purchase.id,
        "purchase_type": purchase.purchase_type,
        "status": purchase.status,
        "efc_amount": (
            float(purchase.efc_amount) if purchase.efc_amount is not None else None
        ),
        "ticket_quantity": purchase.ticket_quantity,
        "uzs_cost": float(purchase.uzs_cost) if purchase.uzs_cost is not None else None,
        "efc_cost": float(purchase.efc_cost) if purchase.efc_cost is not None else None,
        "efc_balance": float(wallet.efc_balance),
        "uzs_balance": float(wallet.uzs_balance),
        "ticket_balance": int(ticket_wallet.tournament_tickets if ticket_wallet else 0),
        "created_at": purchase.created_at,
    }


def _existing(db: Session, idempotency_key: str) -> ShopPurchase | None:
    return db.execute(
        select(ShopPurchase)
        .where(ShopPurchase.idempotency_key == idempotency_key)
        .with_for_update()
    ).scalar_one_or_none()


def _verify_replay(
    purchase: ShopPurchase,
    *,
    telegram_id: int,
    purchase_type: str,
    efc_amount: Decimal | None = None,
    ticket_quantity: int | None = None,
) -> None:
    same = (
        purchase.telegram_id == telegram_id
        and purchase.purchase_type == purchase_type
        and (
            efc_amount is None
            or _decimal(purchase.efc_amount) == efc_amount
        )
        and (
            ticket_quantity is None
            or purchase.ticket_quantity == ticket_quantity
        )
    )
    if not same:
        raise ShopIdempotencyConflict("Idempotency key boshqa xarid uchun ishlatilgan")


def settings(db: Session, *, lock: bool = False) -> ShopSettings:
    query = select(ShopSettings).where(ShopSettings.id == "default")
    if lock:
        query = query.with_for_update()
    value = db.execute(query).scalar_one_or_none()
    if value is not None:
        return value
    value = ShopSettings(
        id="default",
        efc_price_uzs=config.SHOP_EFC_PRICE_UZS,
        ticket_price_efc=config.SHOP_ARENA_TICKET_PRICE_EFC,
    )
    db.add(value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.execute(query).scalar_one()
    db.refresh(value)
    if lock:
        return db.execute(query).scalar_one()
    return value


def update_settings(
    db: Session,
    *,
    admin_id: int,
    efc_price_uzs,
    ticket_price_efc,
) -> ShopSettings:
    efc_price = _decimal(efc_price_uzs)
    ticket_price = _decimal(ticket_price_efc)
    if efc_price <= 0 or ticket_price <= 0:
        raise ShopInvalidAmount("Magazin narxlari 0 dan katta bo‘lishi kerak")
    if efc_price.as_tuple().exponent < -2 or ticket_price.as_tuple().exponent < -2:
        raise ShopInvalidAmount("Magazin narxlari ko‘pi bilan 2 kasr xonali bo‘lishi mumkin")
    value = settings(db, lock=True)
    value.efc_price_uzs = efc_price
    value.ticket_price_efc = ticket_price
    value.updated_by = admin_id
    try:
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise ShopOperationFailed("Magazin narxlari saqlanmadi") from error
    db.refresh(value)
    return value


def settings_result(value: ShopSettings) -> dict:
    return {
        "efc_price_uzs": float(value.efc_price_uzs),
        "ticket_price_efc": float(value.ticket_price_efc),
        "updated_by": value.updated_by,
        "updated_at": value.updated_at,
    }


def catalog(db: Session, telegram_id: int) -> dict:
    wallet = db.get(Wallet, telegram_id)
    if wallet is None:
        raise ShopNotFound("Hamyon topilmadi")
    ticket_wallet = db.get(GameTicketWallet, telegram_id)
    prices = settings(db)
    return {
        "efc_price_uzs": float(prices.efc_price_uzs),
        "ticket_price_efc": float(prices.ticket_price_efc),
        "max_efc_per_purchase": config.SHOP_MAX_EFC_PER_PURCHASE,
        "max_tickets_per_purchase": config.SHOP_MAX_TICKETS_PER_PURCHASE,
        "efc_balance": float(wallet.efc_balance),
        "uzs_balance": float(wallet.uzs_balance),
        "ticket_balance": int(ticket_wallet.tournament_tickets if ticket_wallet else 0),
    }


def buy_efc(
    db: Session,
    *,
    telegram_id: int,
    efc_amount,
    idempotency_key: str,
) -> dict:
    amount = _decimal(efc_amount)
    if amount <= 0 or amount > config.SHOP_MAX_EFC_PER_PURCHASE:
        raise ShopInvalidAmount("EFC miqdori ruxsat etilgan chegaradan tashqarida")
    if amount.as_tuple().exponent < -2:
        raise ShopInvalidAmount("EFC miqdori ko‘pi bilan 2 kasr xonali bo‘lishi mumkin")

    existing = _existing(db, idempotency_key)
    if existing is not None:
        _verify_replay(
            existing,
            telegram_id=telegram_id,
            purchase_type="EFC",
            efc_amount=amount,
        )
        return _result(db, existing)

    try:
        prices = settings(db, lock=True)
        cost = amount * _decimal(prices.efc_price_uzs)
        wallet = db.execute(
            select(Wallet)
            .where(Wallet.telegram_id == telegram_id)
            .with_for_update()
        ).scalar_one_or_none()
        if wallet is None:
            raise ShopNotFound("Hamyon topilmadi")
        uzs_before = _decimal(wallet.uzs_balance)
        efc_before = _decimal(wallet.efc_balance)
        if uzs_before < cost:
            raise ShopInsufficientBalance("UZS balans yetarli emas")

        wallet.uzs_balance = uzs_before - cost
        wallet.efc_balance = efc_before + amount
        purchase = ShopPurchase(
            telegram_id=telegram_id,
            idempotency_key=idempotency_key,
            purchase_type="EFC",
            efc_amount=amount,
            uzs_cost=cost,
            efc_price_uzs=prices.efc_price_uzs,
            status="COMPLETED",
        )
        db.add_all([
            purchase,
            Transaction(
                telegram_id=telegram_id,
                currency="UZS",
                amount=-cost,
                balance_before=uzs_before,
                balance_after=wallet.uzs_balance,
                type="SHOP_EFC_PURCHASE",
                status="SUCCESS",
                description=f"Magazindan {amount} EFC sotib olindi",
            ),
            Transaction(
                telegram_id=telegram_id,
                currency="EFC",
                amount=amount,
                balance_before=efc_before,
                balance_after=wallet.efc_balance,
                type="SHOP_EFC_CREDIT",
                status="SUCCESS",
                description=f"Magazindan {amount} EFC olindi",
            ),
        ])
        db.commit()
        db.refresh(purchase)
        return _result(db, purchase)
    except (ShopNotFound, ShopInsufficientBalance):
        db.rollback()
        raise
    except IntegrityError as error:
        db.rollback()
        replay = _existing(db, idempotency_key)
        if replay is None:
            raise ShopOperationFailed("EFC xaridi bajarilmadi") from error
        _verify_replay(
            replay,
            telegram_id=telegram_id,
            purchase_type="EFC",
            efc_amount=amount,
        )
        return _result(db, replay)
    except SQLAlchemyError as error:
        db.rollback()
        raise ShopOperationFailed("EFC xaridi bajarilmadi") from error


def buy_arena_tickets(
    db: Session,
    *,
    telegram_id: int,
    quantity: int,
    idempotency_key: str,
) -> dict:
    if quantity <= 0 or quantity > config.SHOP_MAX_TICKETS_PER_PURCHASE:
        raise ShopInvalidAmount("Ticket soni ruxsat etilgan chegaradan tashqarida")

    existing = _existing(db, idempotency_key)
    if existing is not None:
        _verify_replay(
            existing,
            telegram_id=telegram_id,
            purchase_type="ARENA_TICKET",
            ticket_quantity=quantity,
        )
        return _result(db, existing)

    try:
        prices = settings(db, lock=True)
        cost = _decimal(prices.ticket_price_efc) * quantity
        wallet = db.execute(
            select(Wallet)
            .where(Wallet.telegram_id == telegram_id)
            .with_for_update()
        ).scalar_one_or_none()
        if wallet is None:
            raise ShopNotFound("Hamyon topilmadi")
        efc_before = _decimal(wallet.efc_balance)
        if efc_before < cost:
            raise ShopInsufficientBalance("EFC balans yetarli emas")

        ticket_wallet = db.execute(
            select(GameTicketWallet)
            .where(GameTicketWallet.telegram_id == telegram_id)
            .with_for_update()
        ).scalar_one_or_none()
        if ticket_wallet is None:
            ticket_wallet = GameTicketWallet(telegram_id=telegram_id)
            db.add(ticket_wallet)
            db.flush()

        wallet.efc_balance = efc_before - cost
        ticket_wallet.tournament_tickets = int(
            ticket_wallet.tournament_tickets or 0
        ) + quantity
        purchase = ShopPurchase(
            telegram_id=telegram_id,
            idempotency_key=idempotency_key,
            purchase_type="ARENA_TICKET",
            ticket_quantity=quantity,
            efc_cost=cost,
            ticket_price_efc=prices.ticket_price_efc,
            status="COMPLETED",
        )
        db.add_all([
            purchase,
            Transaction(
                telegram_id=telegram_id,
                currency="EFC",
                amount=-cost,
                balance_before=efc_before,
                balance_after=wallet.efc_balance,
                type="SHOP_ARENA_TICKET_PURCHASE",
                status="SUCCESS",
                description=f"Magazindan {quantity} Arena Ticket olindi",
            ),
            GameTicketLedger(
                id=str(uuid4()),
                telegram_id=telegram_id,
                ticket_kind=TicketKind.TOURNAMENT,
                operation="SHOP_PURCHASE",
                amount=quantity,
                idempotency_key=f"shop-ticket:{idempotency_key}",
                metadata_json={"efc_cost": str(cost)},
            ),
        ])
        db.commit()
        db.refresh(purchase)
        return _result(db, purchase)
    except (ShopNotFound, ShopInsufficientBalance):
        db.rollback()
        raise
    except IntegrityError as error:
        db.rollback()
        replay = _existing(db, idempotency_key)
        if replay is None:
            raise ShopOperationFailed("Ticket xaridi bajarilmadi") from error
        _verify_replay(
            replay,
            telegram_id=telegram_id,
            purchase_type="ARENA_TICKET",
            ticket_quantity=quantity,
        )
        return _result(db, replay)
    except SQLAlchemyError as error:
        db.rollback()
        raise ShopOperationFailed("Ticket xaridi bajarilmadi") from error
