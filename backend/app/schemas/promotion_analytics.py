from datetime import date, datetime

from pydantic import BaseModel


class PromotionMetrics(BaseModel):
    promotion_id: int
    title: str
    status: str
    priority: int
    views: int
    unique_views: int
    clicks: int
    unique_clicks: int
    unique_users: int
    ctr: float
    conversion_rate: float
    last_viewed_at: datetime | None
    last_clicked_at: datetime | None


class DailyPromotionMetrics(BaseModel):
    date: date
    views: int
    clicks: int
    ctr: float


class AnalyticsSummary(BaseModel):
    views: int
    unique_views: int
    clicks: int
    unique_clicks: int
    unique_users: int
    ctr: float
    conversion_rate: float


class PromotionAnalyticsResponse(BaseModel):
    period: str
    generated_at: datetime
    summary: AnalyticsSummary
    promotions: list[PromotionMetrics]
    top_performing: list[PromotionMetrics]
    worst_performing: list[PromotionMetrics]
    most_clicked: list[PromotionMetrics]
    highest_ctr: list[PromotionMetrics]
    daily: list[DailyPromotionMetrics]
