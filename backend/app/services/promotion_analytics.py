from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.promotion import Promotion, PromotionEvent
from app.services.promotions import synchronize_schedule


PERIODS = {"TODAY", "7D", "30D", "ALL"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def period_start(period: str, now: datetime) -> datetime | None:
    normalized = period.upper()
    if normalized not in PERIODS:
        raise HTTPException(422, "period must be TODAY, 7D, 30D or ALL")
    if normalized == "ALL":
        return None
    today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    days = {"TODAY": 0, "7D": 6, "30D": 29}[normalized]
    return today - timedelta(days=days)


def percentage(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def record_event(db: Session, promotion_id: int, telegram_id: int, event_type: str) -> Promotion:
    synchronize_schedule(db)
    promotion = (
        db.query(Promotion)
        .filter(
            Promotion.id == promotion_id,
            Promotion.status == "ACTIVE",
            Promotion.deleted_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if promotion is None:
        raise HTTPException(404, "Active promotion not found")
    now = utc_now()
    db.add(PromotionEvent(
        promotion_id=promotion.id,
        telegram_id=telegram_id,
        event_type=event_type,
        occurred_at=now,
    ))
    if event_type == "VIEW":
        promotion.view_count += 1
        promotion.last_viewed_at = now
    else:
        promotion.click_count += 1
        promotion.last_clicked_at = now
    db.commit()
    db.refresh(promotion)
    return promotion


def aggregate(db: Session, period: str, now: datetime | None = None) -> dict:
    now = now or utc_now()
    normalized_period = period.upper()
    start = period_start(normalized_period, now)
    promotions = db.query(Promotion).order_by(Promotion.priority.desc(), Promotion.id.desc()).all()
    query = db.query(PromotionEvent).filter(PromotionEvent.occurred_at <= now)
    if start is not None:
        query = query.filter(PromotionEvent.occurred_at >= start)
    events = query.order_by(PromotionEvent.occurred_at.asc()).all()

    buckets = defaultdict(lambda: {
        "views": 0, "clicks": 0, "view_users": set(), "click_users": set(),
        "last_viewed_at": None, "last_clicked_at": None,
    })
    daily = defaultdict(lambda: {"views": 0, "clicks": 0})
    all_view_users = set()
    all_click_users = set()
    for event in events:
        bucket = buckets[event.promotion_id]
        day = event.occurred_at.date()
        if event.event_type == "VIEW":
            bucket["views"] += 1
            bucket["view_users"].add(event.telegram_id)
            bucket["last_viewed_at"] = event.occurred_at
            daily[day]["views"] += 1
            all_view_users.add(event.telegram_id)
        else:
            bucket["clicks"] += 1
            bucket["click_users"].add(event.telegram_id)
            bucket["last_clicked_at"] = event.occurred_at
            daily[day]["clicks"] += 1
            all_click_users.add(event.telegram_id)

    metrics = []
    for promotion in promotions:
        bucket = buckets[promotion.id]
        unique_views = len(bucket["view_users"])
        unique_clicks = len(bucket["click_users"])
        metrics.append({
            "promotion_id": promotion.id,
            "title": promotion.title,
            "status": promotion.status,
            "priority": promotion.priority,
            "views": bucket["views"],
            "unique_views": unique_views,
            "clicks": bucket["clicks"],
            "unique_clicks": unique_clicks,
            "unique_users": len(bucket["view_users"] | bucket["click_users"]),
            "ctr": percentage(bucket["clicks"], bucket["views"]),
            "conversion_rate": percentage(unique_clicks, unique_views),
            "last_viewed_at": bucket["last_viewed_at"],
            "last_clicked_at": bucket["last_clicked_at"],
        })

    if start is not None:
        first_day = start.date()
    elif daily:
        first_day = min(daily)
    else:
        first_day = now.date()
    daily_rows = []
    current = first_day
    while current <= now.date():
        values = daily[current]
        daily_rows.append({
            "date": current,
            "views": values["views"],
            "clicks": values["clicks"],
            "ctr": percentage(values["clicks"], values["views"]),
        })
        current += timedelta(days=1)

    total_views = sum(item["views"] for item in metrics)
    total_clicks = sum(item["clicks"] for item in metrics)
    summary = {
        "views": total_views,
        "unique_views": len(all_view_users),
        "clicks": total_clicks,
        "unique_clicks": len(all_click_users),
        "unique_users": len(all_view_users | all_click_users),
        "ctr": percentage(total_clicks, total_views),
        "conversion_rate": percentage(len(all_click_users), len(all_view_users)),
    }
    active_metrics = [item for item in metrics if item["views"] or item["clicks"]]
    return {
        "period": normalized_period,
        "generated_at": now,
        "summary": summary,
        "promotions": metrics,
        "top_performing": sorted(active_metrics, key=lambda item: (item["clicks"], item["ctr"], item["views"]), reverse=True)[:5],
        "worst_performing": sorted(active_metrics, key=lambda item: (item["ctr"], item["clicks"], item["views"]))[:5],
        "most_clicked": sorted(active_metrics, key=lambda item: (item["clicks"], item["views"]), reverse=True)[:5],
        "highest_ctr": sorted(active_metrics, key=lambda item: (item["ctr"], item["clicks"]), reverse=True)[:5],
        "daily": daily_rows,
    }
