from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.arena_v3 import (
    ArenaV3AIReview, ArenaV3Appeal, ArenaV3Match, ArenaV3MatchEvent,
    ArenaV3MatchScreenshot, ArenaV3Status,
)


ACTIVE_STATUSES = (
    ArenaV3Status.OPEN,
    ArenaV3Status.READY,
    ArenaV3Status.WAITING_ROOM_CODE,
    ArenaV3Status.PLAYING,
    ArenaV3Status.WAITING_SCREENSHOT,
    ArenaV3Status.AI_REVIEW,
)


class ArenaV3Repository:
    """Persistence-only Arena V3 operations. Callers own commit/rollback."""

    def __init__(self, db: Session):
        self.db = db

    def add_match(self, match: ArenaV3Match) -> ArenaV3Match:
        self.db.add(match)
        self.db.flush()
        return match

    def get_match(self, match_id: int) -> ArenaV3Match | None:
        return self.db.get(ArenaV3Match, match_id)

    def get_match_for_update(self, match_id: int) -> ArenaV3Match | None:
        return self.db.execute(
            select(ArenaV3Match).where(ArenaV3Match.id == match_id).with_for_update()
        ).scalar_one_or_none()

    def get_by_owner_idempotency(self, owner_id: int, key: str) -> ArenaV3Match | None:
        return self.db.execute(
            select(ArenaV3Match).where(
                ArenaV3Match.owner_id == owner_id,
                ArenaV3Match.idempotency_key == key,
            )
        ).scalar_one_or_none()

    def get_active_for_player(self, player_id: int) -> ArenaV3Match | None:
        return self.db.execute(
            select(ArenaV3Match).where(
                ArenaV3Match.status.in_(ACTIVE_STATUSES),
                or_(ArenaV3Match.owner_id == player_id, ArenaV3Match.opponent_id == player_id),
            ).with_for_update()
        ).scalars().first()

    def find_active_for_player(self, player_id: int) -> ArenaV3Match | None:
        return self.db.execute(
            select(ArenaV3Match).where(
                ArenaV3Match.status.in_(ACTIVE_STATUSES),
                or_(ArenaV3Match.owner_id == player_id, ArenaV3Match.opponent_id == player_id),
            )
        ).scalars().first()

    def list_open(self, *, limit: int = 20, offset: int = 0) -> Sequence[ArenaV3Match]:
        return self.db.execute(
            select(ArenaV3Match)
            .where(ArenaV3Match.status == ArenaV3Status.OPEN)
            .order_by(ArenaV3Match.created_at.asc(), ArenaV3Match.id.asc())
            .offset(offset).limit(limit)
        ).scalars().all()

    def add_screenshot(self, value: ArenaV3MatchScreenshot) -> ArenaV3MatchScreenshot:
        self.db.add(value)
        self.db.flush()
        return value

    def get_player_screenshot(
        self, match_id: int, player_id: int
    ) -> ArenaV3MatchScreenshot | None:
        return self.db.execute(
            select(ArenaV3MatchScreenshot).where(
                ArenaV3MatchScreenshot.match_id == match_id,
                ArenaV3MatchScreenshot.player_id == player_id,
            )
        ).scalar_one_or_none()

    def list_screenshots(self, match_id: int) -> Sequence[ArenaV3MatchScreenshot]:
        return self.db.execute(
            select(ArenaV3MatchScreenshot)
            .where(ArenaV3MatchScreenshot.match_id == match_id)
            .order_by(ArenaV3MatchScreenshot.uploaded_at, ArenaV3MatchScreenshot.id)
        ).scalars().all()

    def add_ai_review(self, value: ArenaV3AIReview) -> ArenaV3AIReview:
        self.db.add(value)
        self.db.flush()
        return value

    def get_latest_ai_review(self, match_id: int) -> ArenaV3AIReview | None:
        return self.db.execute(
            select(ArenaV3AIReview)
            .where(ArenaV3AIReview.match_id == match_id)
            .order_by(ArenaV3AIReview.id.desc())
        ).scalars().first()

    def get_ai_review_for_update(self, review_id: int) -> ArenaV3AIReview | None:
        return self.db.execute(
            select(ArenaV3AIReview)
            .where(ArenaV3AIReview.id == review_id)
            .with_for_update()
        ).scalar_one_or_none()

    def add_appeal(self, value: ArenaV3Appeal) -> ArenaV3Appeal:
        self.db.add(value)
        self.db.flush()
        return value

    def add_event(self, value: ArenaV3MatchEvent) -> ArenaV3MatchEvent:
        self.db.add(value)
        self.db.flush()
        return value

    def get_event_by_idempotency(
        self, match_id: int, idempotency_key: str
    ) -> ArenaV3MatchEvent | None:
        return self.db.execute(
            select(ArenaV3MatchEvent).where(
                ArenaV3MatchEvent.match_id == match_id,
                ArenaV3MatchEvent.idempotency_key == idempotency_key,
            )
        ).scalar_one_or_none()

    def flush(self) -> None:
        self.db.flush()
