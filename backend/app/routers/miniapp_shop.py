from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.shop import (
    MiniAppBuyArenaTicketRequest,
    MiniAppBuyEFCRequest,
    MiniAppShopSettingsUpdate,
    ShopCatalogResponse,
    ShopPurchaseResponse,
    ShopSettingsResponse,
)
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


router = APIRouter(prefix="/wallet-shop", tags=["MiniApp Wallet Shop"])
admin_router = APIRouter(prefix="/admin/wallet-shop", tags=["MiniApp Wallet Shop Admin"])


def _idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    key = (value or "").strip()
    if not key or len(key) > 96:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Yaroqli Idempotency-Key talab qilinadi",
        )
    return key


def _raise_shop_error(error: Exception):
    if isinstance(error, ShopNotFound):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, ShopNotConfigured):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, ShopInvalidAmount):
        raise HTTPException(status_code=422, detail=str(error)) from error
    if isinstance(error, ShopInsufficientBalance):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, ShopIdempotencyConflict):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, ShopOperationFailed):
        raise HTTPException(status_code=500, detail=str(error)) from error
    raise error


@router.get("/catalog", response_model=ShopCatalogResponse)
def miniapp_shop_catalog(
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        return catalog(db, current_user.telegram_id)
    except Exception as error:
        _raise_shop_error(error)


@router.post("/buy-efc", response_model=ShopPurchaseResponse)
def miniapp_shop_buy_efc(
    data: MiniAppBuyEFCRequest,
    idempotency_key: str = Depends(_idempotency_key),
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        return buy_efc(
            db,
            telegram_id=current_user.telegram_id,
            efc_amount=data.efc_amount,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise_shop_error(error)


@router.post("/buy-ticket", response_model=ShopPurchaseResponse)
def miniapp_shop_buy_ticket(
    data: MiniAppBuyArenaTicketRequest,
    idempotency_key: str = Depends(_idempotency_key),
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        return buy_arena_tickets(
            db,
            telegram_id=current_user.telegram_id,
            quantity=data.quantity,
            idempotency_key=idempotency_key,
        )
    except Exception as error:
        _raise_shop_error(error)


@admin_router.get("/settings", response_model=ShopSettingsResponse)
def miniapp_shop_admin_settings(
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    try:
        return settings_result(settings(db))
    except Exception as error:
        _raise_shop_error(error)


@admin_router.put("/settings", response_model=ShopSettingsResponse)
def miniapp_shop_admin_update_settings(
    data: MiniAppShopSettingsUpdate,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    try:
        return settings_result(update_settings(
            db,
            admin_id=admin.telegram_id,
            efc_price_uzs=data.efc_price_uzs,
            ticket_price_efc=data.ticket_price_efc,
        ))
    except Exception as error:
        _raise_shop_error(error)
