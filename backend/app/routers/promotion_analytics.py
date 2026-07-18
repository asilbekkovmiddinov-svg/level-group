import csv
from io import StringIO

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.promotion_analytics import PromotionAnalyticsResponse
from app.services.promotion_analytics import aggregate, record_event


admin_router = APIRouter(prefix="/admin/promotions/analytics", tags=["Marketing CMS Analytics"])
public_router = APIRouter(prefix="/promotions", tags=["Promotions"])


@public_router.post("/{promotion_id}/view", status_code=204)
def promotion_view(
    promotion_id: int,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    record_event(db, promotion_id, current_user.telegram_id, "VIEW")


@public_router.post("/{promotion_id}/click", status_code=204)
def promotion_click(
    promotion_id: int,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    record_event(db, promotion_id, current_user.telegram_id, "CLICK")


@admin_router.get("", response_model=PromotionAnalyticsResponse)
def promotion_analytics(
    period: str = "7D",
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    return aggregate(db, period)


@admin_router.get("/export")
def promotion_analytics_export(
    period: str = "7D",
    _admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    report = aggregate(db, period)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "promotion_id", "title", "status", "priority", "views", "unique_views",
        "clicks", "unique_clicks", "unique_users", "ctr_percent",
        "conversion_rate_percent", "last_viewed_at", "last_clicked_at",
    ])
    for item in report["promotions"]:
        writer.writerow([
            item["promotion_id"], item["title"], item["status"], item["priority"],
            item["views"], item["unique_views"], item["clicks"], item["unique_clicks"],
            item["unique_users"], item["ctr"], item["conversion_rate"],
            item["last_viewed_at"] or "", item["last_clicked_at"] or "",
        ])
    filename = f"promotion-analytics-{report['period'].lower()}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
