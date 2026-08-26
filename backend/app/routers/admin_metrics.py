from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.arena_v3 import ArenaV3Match, ArenaV3Status
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet


router = APIRouter(prefix="/admin/metrics", tags=["Admin Metrics"])
ACTIVE_WINDOW_DAYS = 30


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("/arena/matches/{match_id}/cancel")
def emergency_cancel_arena_match(
    match_id: int,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    """Admin-only emergency cancel for a stuck Arena match. No ticket refund."""
    match = db.execute(
        select(ArenaV3Match)
        .where(ArenaV3Match.id == match_id)
        .with_for_update()
    ).scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=404, detail="Arena match topilmadi")
    if match.status == ArenaV3Status.FINISHED:
        raise HTTPException(status_code=409, detail="Yakunlangan matchni bekor qilib bo‘lmaydi")
    if match.status == ArenaV3Status.CANCELLED:
        return {"ok": True, "match_id": match.id, "status": "CANCELLED", "already_cancelled": True}

    match.status = ArenaV3Status.CANCELLED
    match.cancel_reason = f"Admin emergency cancel by {admin.telegram_id}"
    match.finished_at = datetime.now(timezone.utc)
    match.version = (match.version or 0) + 1
    db.commit()
    return {"ok": True, "match_id": match.id, "status": "CANCELLED", "tickets_refunded": False}


@router.get("/users")
def user_metrics(
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    active_since = now - timedelta(days=ACTIVE_WINDOW_DAYS)
    total_users = db.query(func.count(User.telegram_id)).scalar() or 0
    monthly_active_users = (
        db.query(func.count(User.telegram_id))
        .filter(User.last_seen_at.isnot(None), User.last_seen_at >= active_since)
        .scalar()
        or 0
    )
    return {
        "total_users": int(total_users),
        "monthly_active_users": int(monthly_active_users),
        "active_window_days": ACTIVE_WINDOW_DAYS,
        "generated_at": now,
    }


@router.get("/users/list")
def list_users(
    q: str = Query(default="", max_length=100),
    status: str = Query(default="ALL", pattern="^(ALL|ACTIVE|INACTIVE)$"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=50),
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    active_since = now - timedelta(days=ACTIVE_WINDOW_DAYS)
    query = db.query(User)
    search = q.strip()
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(
            User.username.ilike(pattern),
            User.first_name.ilike(pattern),
            User.last_name.ilike(pattern),
            cast(User.telegram_id, String).ilike(pattern),
        ))
    if status == "ACTIVE":
        query = query.filter(User.last_seen_at.isnot(None), User.last_seen_at >= active_since)
    elif status == "INACTIVE":
        query = query.filter(or_(User.last_seen_at.is_(None), User.last_seen_at < active_since))

    total = query.count()
    users = (
        query.order_by(User.last_seen_at.is_(None), User.last_seen_at.desc(), User.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "items": [
            {
                "telegram_id": user.telegram_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "language": user.language,
                "created_at": user.created_at,
                "last_seen_at": user.last_seen_at,
                "is_active": bool(_as_utc(user.last_seen_at) and _as_utc(user.last_seen_at) >= active_since),
            }
            for user in users
        ],
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": (total + per_page - 1) // per_page,
        "active_window_days": ACTIVE_WINDOW_DAYS,
    }


@router.get("/users/audit")
def user_wallet_audit(
    q: str = Query(min_length=1, max_length=100),
    limit: int = Query(default=100, ge=1, le=500),
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    """Admin-only wallet audit by Telegram username or Telegram ID."""
    search = q.strip().lstrip("@")
    user = None
    if search.isdigit():
        user = db.get(User, int(search))
    if user is None:
        user = db.query(User).filter(func.lower(User.username) == search.lower()).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    wallet = db.get(Wallet, user.telegram_id)
    transactions = (
        db.query(Transaction)
        .filter(Transaction.telegram_id == user.telegram_id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit)
        .all()
    )
    referral_transactions = [
        tx for tx in transactions if (tx.type or "").startswith("REFERRAL_")
    ]

    return {
        "user": {
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        },
        "wallet": None if wallet is None else {
            "efc_balance": wallet.efc_balance,
            "uzs_balance": wallet.uzs_balance,
            "locked_efc": wallet.locked_efc,
            "locked_reward_efc": wallet.locked_reward_efc,
            "locked_uzs": wallet.locked_uzs,
        },
        "referral_earned_uzs": sum(
            (tx.amount for tx in referral_transactions if tx.currency == "UZS"),
            start=0,
        ),
        "transactions": [
            {
                "id": tx.id,
                "currency": tx.currency,
                "amount": tx.amount,
                "balance_before": tx.balance_before,
                "balance_after": tx.balance_after,
                "type": tx.type,
                "status": tx.status,
                "description": tx.description,
                "created_at": tx.created_at,
            }
            for tx in transactions
        ],
    }
