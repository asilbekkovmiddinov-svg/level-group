from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.arena_promocode import ArenaTicketPromocode
from app.schemas.arena_promocode import ArenaPromocodeCreate, ArenaPromocodeResponse


router = APIRouter(prefix="/admin/arena-promocodes", tags=["Arena Promocodes Admin"])


@router.get("", response_model=list[ArenaPromocodeResponse])
def list_promocodes(
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return list(db.execute(
        select(ArenaTicketPromocode).order_by(ArenaTicketPromocode.created_at.desc())
    ).scalars())


@router.post("", response_model=ArenaPromocodeResponse, status_code=201)
def create_promocode(
    payload: ArenaPromocodeCreate,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    promo = ArenaTicketPromocode(
        code=payload.code,
        ticket_amount=payload.ticket_amount,
        usage_limit=payload.usage_limit,
        expires_at=payload.expires_at,
        created_by=admin.telegram_id,
        is_active=True,
    )
    db.add(promo)
    try:
        db.commit()
        db.refresh(promo)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Promokod allaqachon mavjud") from exc
    return promo


@router.post("/{promocode_id}/activate", response_model=ArenaPromocodeResponse)
def activate_promocode(
    promocode_id: str,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    promo = db.get(ArenaTicketPromocode, promocode_id)
    if promo is None:
        raise HTTPException(404, "Promokod topilmadi")
    promo.is_active = True
    db.commit()
    db.refresh(promo)
    return promo


@router.post("/{promocode_id}/deactivate", response_model=ArenaPromocodeResponse)
def deactivate_promocode(
    promocode_id: str,
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    promo = db.get(ArenaTicketPromocode, promocode_id)
    if promo is None:
        raise HTTPException(404, "Promokod topilmadi")
    promo.is_active = False
    db.commit()
    db.refresh(promo)
    return promo
