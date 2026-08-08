from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.user import User


router = APIRouter(prefix="/admin/metrics", tags=["Admin Metrics"])
ACTIVE_WINDOW_DAYS = 30


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
