from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.arena_v3 import (
    ArenaV3AIReview, ArenaV3Appeal, ArenaV3AppealStatus,
    ArenaV3Match, ArenaV3MatchEvent,
    ArenaV3AIReviewStatus, ArenaV3MatchScreenshot,
    ArenaV3NotificationDelivery, ArenaV3Stats, ArenaV3Status,
    ArenaV4AdminReview, ArenaV4AdminReviewStatus, ArenaV4ResultRevision,
    ArenaV4ReviewType, ArenaV4SettlementOperation,
)


ACTIVE_STATUSES = (
    ArenaV3Status.OPEN,
    ArenaV3Status.READY,
    ArenaV3Status.WAITING_ROOM_CODE,
    ArenaV3Status.PLAYING,
    ArenaV3Status.WAITING_SCREENSHOT,
    ArenaV3Status.WAITING_ADMIN,
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

    def add_admin_review(self, value: ArenaV4AdminReview) -> ArenaV4AdminReview:
        self.db.add(value)
        self.db.flush()
        return value

    def get_admin_review(self, review_id: int) -> ArenaV4AdminReview | None:
        return self.db.get(ArenaV4AdminReview, review_id)

    def get_admin_review_for_update(
        self, review_id: int
    ) -> ArenaV4AdminReview | None:
        return self.db.execute(
            select(ArenaV4AdminReview)
            .where(ArenaV4AdminReview.id == review_id)
            .with_for_update()
        ).scalar_one_or_none()

    def get_initial_admin_review(
        self, match_id: int, result_version: int = 0
    ) -> ArenaV4AdminReview | None:
        return self.db.execute(
            select(ArenaV4AdminReview).where(
                ArenaV4AdminReview.match_id == match_id,
                ArenaV4AdminReview.review_type == ArenaV4ReviewType.INITIAL,
                ArenaV4AdminReview.result_version == result_version,
            )
        ).scalar_one_or_none()

    def list_admin_reviews(
        self,
        *,
        status: ArenaV4AdminReviewStatus | None,
        review_type: ArenaV4ReviewType | None,
        limit: int,
        offset: int,
    ) -> Sequence[ArenaV4AdminReview]:
        query = select(ArenaV4AdminReview)
        if status is not None:
            query = query.where(ArenaV4AdminReview.status == status)
        if review_type is not None:
            query = query.where(ArenaV4AdminReview.review_type == review_type)
        return self.db.execute(
            query.order_by(
                ArenaV4AdminReview.created_at.asc(), ArenaV4AdminReview.id.asc()
            ).offset(offset).limit(limit)
        ).scalars().all()

    def add_result_revision(
        self, value: ArenaV4ResultRevision
    ) -> ArenaV4ResultRevision:
        self.db.add(value)
        self.db.flush()
        return value

    def add_settlement_operation(
        self, value: ArenaV4SettlementOperation
    ) -> ArenaV4SettlementOperation:
        self.db.add(value)
        self.db.flush()
        return value

    def list_settlement_operations_for_update(
        self, match_id: int, result_version: int
    ):
        return self.db.execute(
            select(ArenaV4SettlementOperation)
            .where(
                ArenaV4SettlementOperation.match_id == match_id,
                ArenaV4SettlementOperation.result_version == result_version,
            )
            .order_by(ArenaV4SettlementOperation.id)
            .with_for_update()
        ).scalars().all()

    def list_finished_matches_for_player(self, player_id: int):
        return self.db.execute(
            select(ArenaV3Match)
            .where(
                ArenaV3Match.status == ArenaV3Status.FINISHED,
                or_(
                    ArenaV3Match.owner_id == player_id,
                    ArenaV3Match.opponent_id == player_id,
                ),
            )
            .order_by(
                ArenaV3Match.finished_at.asc(),
                ArenaV3Match.id.asc(),
            )
        ).scalars().all()

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

    def claim_pending_ai_review(self) -> ArenaV3AIReview | None:
        return self.db.execute(
            select(ArenaV3AIReview)
            .where(ArenaV3AIReview.status == ArenaV3AIReviewStatus.PENDING)
            .order_by(ArenaV3AIReview.created_at, ArenaV3AIReview.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).scalar_one_or_none()

    def add_appeal(self, value: ArenaV3Appeal) -> ArenaV3Appeal:
        self.db.add(value)
        self.db.flush()
        return value

    def get_open_appeal(self, match_id: int) -> ArenaV3Appeal | None:
        return self.db.execute(
            select(ArenaV3Appeal).where(
                ArenaV3Appeal.match_id == match_id,
                ArenaV3Appeal.status == ArenaV3AppealStatus.OPEN,
            )
        ).scalars().first()

    def get_appeal_for_update(self, match_id: int) -> ArenaV3Appeal | None:
        return self.db.execute(
            select(ArenaV3Appeal)
            .where(ArenaV3Appeal.match_id == match_id)
            .order_by(ArenaV3Appeal.id.desc())
            .with_for_update()
        ).scalars().first()

    def get_appeal(self, match_id: int) -> ArenaV3Appeal | None:
        return self.db.execute(
            select(ArenaV3Appeal)
            .where(ArenaV3Appeal.match_id == match_id)
            .order_by(ArenaV3Appeal.id.desc())
        ).scalars().first()

    def get_appeal_by_idempotency(
        self, match_id: int, key: str
    ) -> ArenaV3MatchEvent | None:
        return self.get_event_by_idempotency(match_id, f"appeal-upload:{key}")

    def get_stats_for_update(self, player_id: int) -> ArenaV3Stats | None:
        return self.db.execute(
            select(ArenaV3Stats)
            .where(ArenaV3Stats.player_id == player_id)
            .with_for_update()
        ).scalar_one_or_none()

    def add_stats(self, value: ArenaV3Stats) -> ArenaV3Stats:
        self.db.add(value)
        self.db.flush()
        return value

    def get_stats(self, player_id: int) -> ArenaV3Stats | None:
        return self.db.get(ArenaV3Stats, player_id)

    def list_history(
        self, player_id: int, *, limit: int = 50, offset: int = 0
    ) -> Sequence[ArenaV3Match]:
        return self.db.execute(
            select(ArenaV3Match)
            .where(
                ArenaV3Match.status.in_(
                    (ArenaV3Status.FINISHED, ArenaV3Status.CANCELLED)
                ),
                or_(
                    ArenaV3Match.owner_id == player_id,
                    ArenaV3Match.opponent_id == player_id,
                ),
            )
            .order_by(ArenaV3Match.updated_at.desc(), ArenaV3Match.id.desc())
            .offset(offset).limit(limit)
        ).scalars().all()

    def add_notification(
        self, value: ArenaV3NotificationDelivery
    ) -> ArenaV3NotificationDelivery:
        self.db.add(value)
        self.db.flush()
        return value

    def get_notification_by_dedup(
        self, dedup_key: str
    ) -> ArenaV3NotificationDelivery | None:
        return self.db.execute(
            select(ArenaV3NotificationDelivery).where(
                ArenaV3NotificationDelivery.dedup_key == dedup_key
            )
        ).scalar_one_or_none()

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
