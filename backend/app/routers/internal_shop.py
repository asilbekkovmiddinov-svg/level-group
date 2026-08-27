from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.shop import BuyArenaTicketRequest, BuyEFCRequest, ShopSettingsUpdate
from app.services.shop import (
    ShopIdempotencyConflict,
    ShopInsufficientBalance,
    ShopInvalidAmount,
    ShopNotConfigured,
    ShopNotFound,
    ShopOperationFailed,
    buy_arena_tickets,
    buy_efc,
    catalog,
    settings,
    settings_result,
    update_settings,
)


router = APIRouter(
    prefix="/internal/shop",
    tags=["Internal Shop"],
    dependencies=[Depends(require_internal_api_key)],
)


def _idempotency_key(value: str | None) -> str:
    key = (value or "").strip()
    if not key or len(key) > 96:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Yaroqli Idempotency-Key talab qilinadi",
        )
    return key


def _raise_shop_error(error: Exception):
    if isinstance(error, ShopNotFound):
        raise HTTPException(status_code=404, detail=str(error))
    if isinstance(error, ShopNotConfigured):
        raise HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ShopInvalidAmount):
        raise HTTPException(status_code=422, detail=str(error))
    if isinstance(error, ShopInsufficientBalance):
        raise HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ShopIdempotencyConflict):
        raise HTTPException(status_code=409, detail=str(error))
    if isinstance(error, ShopOperationFailed):
        raise HTTPException(status_code=500, detail=str(error))
    raise error


@router.get("/catalog/{telegram_id}")
def shop_catalog(telegram_id: int, db: Session = Depends(get_db)):
    if telegram_id <= 0:
        raise HTTPException(status_code=422, detail="Telegram ID noto‘g‘ri")
    try:
        return {"success": True, "data": catalog(db, telegram_id)}
    except Exception as error:
        _raise_shop_error(error)


@router.get("/admin/settings")
def shop_admin_settings(db: Session = Depends(get_db)):
    try:
        return {"success": True, "data": settings_result(settings(db))}
    except Exception as error:
        _raise_shop_error(error)


@router.put("/admin/settings")
def shop_admin_update_settings(
    data: ShopSettingsUpdate,
    db: Session = Depends(get_db),
):
    try:
        value = update_settings(
            db,
            admin_id=data.admin_id,
            efc_price_uzs=data.efc_price_uzs,
            ticket_price_efc=data.ticket_price_efc,
        )
        return {"success": True, "data": settings_result(value)}
    except Exception as error:
        _raise_shop_error(error)


@router.post("/buy-efc")
def shop_buy_efc(
    data: BuyEFCRequest,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
    db: Session = Depends(get_db),
):
    try:
        result = buy_efc(
            db,
            telegram_id=data.telegram_id,
            efc_amount=data.efc_amount,
            idempotency_key=_idempotency_key(idempotency_key),
        )
        return {"success": True, "data": result}
    except Exception as error:
        _raise_shop_error(error)


@router.post("/buy-ticket")
def shop_buy_ticket(
    data: BuyArenaTicketRequest,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key")
    ] = None,
    db: Session = Depends(get_db),
):
    try:
        result = buy_arena_tickets(
            db,
            telegram_id=data.telegram_id,
            quantity=data.quantity,
            idempotency_key=_idempotency_key(idempotency_key),
        )
        return {"success": True, "data": result}
    except Exception as error:
        _raise_shop_error(error)
