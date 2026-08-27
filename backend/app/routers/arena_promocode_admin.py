from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.arena_promocode import ArenaTicketPromocode
from app.models.arena_v3 import ArenaV3Match, ArenaV3Status
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


@router.post("/matches/{match_id}/cancel")
def cancel_arena_match(
    match_id: int,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    """Admin-only emergency cancel. Does not refund tickets."""
    match = db.execute(
        select(ArenaV3Match)
        .where(ArenaV3Match.id == match_id)
        .with_for_update()
    ).scalar_one_or_none()
    if match is None:
        raise HTTPException(404, "Arena match topilmadi")
    if match.status == ArenaV3Status.FINISHED:
        raise HTTPException(409, "Yakunlangan matchni bekor qilib bo‘lmaydi")
    if match.status == ArenaV3Status.CANCELLED:
        return {"ok": True, "match_id": match.id, "status": "CANCELLED", "already_cancelled": True}

    match.status = ArenaV3Status.CANCELLED
    match.cancel_reason = f"Admin emergency cancel by {admin.telegram_id}"
    match.finished_at = datetime.now(timezone.utc)
    match.version = (match.version or 0) + 1
    db.commit()
    return {"ok": True, "match_id": match.id, "status": "CANCELLED", "tickets_refunded": False}
