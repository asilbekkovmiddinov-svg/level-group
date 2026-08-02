from datetime import timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.models.user import User
from app.services.arena_time import utc_now


router = APIRouter(prefix="/admin/users", tags=["Admin Users"])


class AdminUserStatsResponse(BaseModel):
    total_users: int
    online_users: int


@router.get("/stats", response_model=AdminUserStatsResponse)
def get_admin_user_stats(
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
) -> AdminUserStatsResponse:
    online_limit = utc_now() - timedelta(minutes=5)
    total_users = db.scalar(select(func.count()).select_from(User)) or 0
    online_users = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.is_banned.is_(False), User.last_seen_at >= online_limit)
    ) or 0
    return AdminUserStatsResponse(
        total_users=int(total_users),
        online_users=int(online_users),
    )
