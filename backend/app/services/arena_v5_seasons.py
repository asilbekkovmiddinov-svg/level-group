from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core import config
from app.models.arena_v3 import ArenaV3Match, ArenaV3RankingPrize, ArenaV5QueueEntry
from app.models.arena_v5_season import (
    ArenaV5ReferralPoint,
    ArenaV5Season,
    ArenaV5SeasonStatus,
)
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3NotFound


ARENA_V5_WIN_POINTS = 3
ARENA_V5_DRAW_POINTS = 1
ARENA_V5_LOSS_POINTS = 0
ARENA_V5_REFERRAL_POINTS = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def legacy_season_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or utc_now()
    configured_end = config.ARENA_V5_SEASON_END_AT
    if configured_end:
        try:
            end = datetime.fromisoformat(configured_end.replace("Z", "+00:00"))
            return _aware(end) - timedelta(days=7), _aware(end)
        except ValueError:
            pass
    start = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return start, start + timedelta(days=7)


class ArenaV5SeasonService:
    def __init__(self, db):
        self.db = db

    def finish_expired(self, now: datetime | None = None) -> int:
        now = now or utc_now()
        seasons = self.db.execute(
            select(ArenaV5Season).where(
                ArenaV5Season.status == ArenaV5SeasonStatus.ACTIVE,
                ArenaV5Season.ends_at <= now,
            )
        ).scalars().all()
        for season in seasons:
            season.status = ArenaV5SeasonStatus.FINISHED
            season.finished_at = season.ends_at
        if seasons:
            self.db.flush()
        return len(seasons)

    def active(self, now: datetime | None = None) -> ArenaV5Season | None:
        now = now or utc_now()
        self.finish_expired(now)
        return self.db.execute(
            select(ArenaV5Season)
            .where(
                ArenaV5Season.status == ArenaV5SeasonStatus.ACTIVE,
                ArenaV5Season.starts_at <= now,
                ArenaV5Season.ends_at > now,
            )
            .order_by(ArenaV5Season.starts_at.desc(), ArenaV5Season.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def latest(self) -> ArenaV5Season | None:
        self.finish_expired()
        return self.db.execute(
            select(ArenaV5Season)
            .order_by(ArenaV5Season.starts_at.desc(), ArenaV5Season.id.desc())
            .limit(1)
        ).scalar_one_or_none()

    def get(self, season_id: int) -> ArenaV5Season:
        self.finish_expired()
        season = self.db.get(ArenaV5Season, season_id)
        if season is None:
            raise ArenaV3NotFound("Arena mavsumi topilmadi")
        return season

    def create(
        self,
        *,
        name: str,
        duration_days: int,
        created_by: int,
        prize_text: str | None = None,
        now: datetime | None = None,
    ) -> ArenaV5Season:
        now = now or utc_now()
        normalized_name = " ".join(name.strip().split())
        if not normalized_name:
            raise ArenaV3Conflict("Arena mavsumi nomini kiriting")
        if not 1 <= int(duration_days) <= 365:
            raise ArenaV3Conflict("Arena davomiyligi 1 kundan 365 kungacha bo‘lishi kerak")
        self.finish_expired(now)
        existing = self.db.execute(
            select(ArenaV5Season.id).where(
                ArenaV5Season.status == ArenaV5SeasonStatus.ACTIVE
            )
        ).first()
        if existing:
            raise ArenaV3Conflict("Avval ishlab turgan Arena mavsumini yakunlang")
        self.db.query(ArenaV5QueueEntry).delete(synchronize_session=False)
        season = ArenaV5Season(
            name=normalized_name,
            status=ArenaV5SeasonStatus.ACTIVE,
            duration_days=int(duration_days),
            points_for_win=ARENA_V5_WIN_POINTS,
            points_for_draw=ARENA_V5_DRAW_POINTS,
            points_for_loss=ARENA_V5_LOSS_POINTS,
            referral_points=ARENA_V5_REFERRAL_POINTS,
            prize_text=(prize_text or "").strip() or None,
            starts_at=now,
            ends_at=now + timedelta(days=int(duration_days)),
            created_by=created_by,
        )
        self.db.add(season)
        self.db.commit()
        self.db.refresh(season)
        return season

    def finish(
        self,
        season_id: int,
        *,
        now: datetime | None = None,
    ) -> ArenaV5Season:
        now = now or utc_now()
        season = self.get(season_id)
        if season.status == ArenaV5SeasonStatus.FINISHED:
            self.db.commit()
            self.db.refresh(season)
            return season
        season.status = ArenaV5SeasonStatus.FINISHED
        season.ends_at = min(_aware(season.ends_at), now)
        season.finished_at = now
        self.db.query(ArenaV5QueueEntry).delete(synchronize_session=False)
        self.db.commit()
        self.db.refresh(season)
        return season

    def update_duration(
        self,
        season_id: int,
        *,
        duration_days: int,
        now: datetime | None = None,
    ) -> ArenaV5Season:
        now = now or utc_now()
        if not 1 <= int(duration_days) <= 365:
            raise ArenaV3Conflict("Arena davomiyligi 1 kundan 365 kungacha bo‘lishi kerak")
        season = self.get(season_id)
        if season.status != ArenaV5SeasonStatus.ACTIVE:
            raise ArenaV3Conflict("Faqat faol Arena mavsumi muddatini o‘zgartirish mumkin")
        new_end = _aware(season.starts_at) + timedelta(days=int(duration_days))
        if new_end <= now:
            raise ArenaV3Conflict("Tanlangan muddat allaqachon tugagan; kattaroq kun kiriting")
        season.duration_days = int(duration_days)
        season.ends_at = new_end
        self.db.commit()
        self.db.refresh(season)
        return season

    def summary(self, season: ArenaV5Season) -> dict:
        match_count = self.db.scalar(
            select(func.count(ArenaV3Match.id)).where(
                ArenaV3Match.arena_v5_season_id == season.id
            )
        ) or 0
        referral_count = self.db.scalar(
            select(func.count(ArenaV5ReferralPoint.id)).where(
                ArenaV5ReferralPoint.season_id == season.id
            )
        ) or 0
        return {
            "id": season.id,
            "name": season.name,
            "status": season.status.value if hasattr(season.status, "value") else season.status,
            "duration_days": season.duration_days,
            "starts_at": season.starts_at,
            "ends_at": season.ends_at,
            "finished_at": season.finished_at,
            "prize_text": season.prize_text,
            "points_for_win": season.points_for_win,
            "points_for_draw": season.points_for_draw,
            "points_for_loss": season.points_for_loss,
            "referral_points": season.referral_points,
            "match_count": int(match_count),
            "referral_count": int(referral_count),
        }

    def list(self, *, limit: int = 50) -> list[dict]:
        self.finish_expired()
        seasons = self.db.execute(
            select(ArenaV5Season)
            .order_by(ArenaV5Season.starts_at.desc(), ArenaV5Season.id.desc())
            .limit(limit)
        ).scalars().all()
        self.db.commit()
        return [self.summary(season) for season in seasons]


def award_active_arena_referral_points(db, referral) -> ArenaV5ReferralPoint | None:
    season = ArenaV5SeasonService(db).active()
    if season is None:
        return None
    existing = db.execute(
        select(ArenaV5ReferralPoint).where(
            ArenaV5ReferralPoint.season_id == season.id,
            ArenaV5ReferralPoint.referral_id == referral.id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    award = ArenaV5ReferralPoint(
        season_id=season.id,
        referral_id=referral.id,
        referrer_telegram_id=referral.referrer_telegram_id,
        referred_telegram_id=referral.referred_telegram_id,
        points=season.referral_points,
    )
    db.add(award)
    db.flush()
    return award


def seed_arena_v5_season(db) -> ArenaV5Season | None:
    if db.execute(select(ArenaV5Season.id).limit(1)).first():
        return None
    now = utc_now()
    start, end = legacy_season_window(now)
    if end <= now:
        return None
    prize = db.get(ArenaV3RankingPrize, "weekly")
    season = ArenaV5Season(
        name=config.ARENA_V5_SEASON_NAME or "Haftalik Arena",
        status=ArenaV5SeasonStatus.ACTIVE,
        duration_days=max(1, (end.date() - start.date()).days),
        points_for_win=ARENA_V5_WIN_POINTS,
        points_for_draw=ARENA_V5_DRAW_POINTS,
        points_for_loss=ARENA_V5_LOSS_POINTS,
        referral_points=ARENA_V5_REFERRAL_POINTS,
        prize_text=prize.prize_text if prize else None,
        starts_at=start,
        ends_at=end,
        created_by=None,
    )
    db.add(season)
    db.flush()
    db.query(ArenaV3Match).filter(
        ArenaV3Match.flow_version == 5,
        ArenaV3Match.arena_v5_season_id.is_(None),
        ArenaV3Match.created_at >= start,
        ArenaV3Match.created_at < end,
    ).update({ArenaV3Match.arena_v5_season_id: season.id}, synchronize_session=False)
    db.commit()
    db.refresh(season)
    return season
