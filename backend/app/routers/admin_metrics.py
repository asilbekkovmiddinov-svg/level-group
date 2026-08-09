from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.user import User


router = APIRouter(prefix="/admin/metrics", tags=["Admin Metrics"])
ACTIVE_WINDOW_DAYS = 30


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
