from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.arena_v3 import (
    ArenaV3AppealStatus,
    ArenaV3Status,
    ArenaV4AdminReviewStatus,
    ArenaV4AppealReviewAction,
    ArenaV4ResultType,
    ArenaV4ReviewType,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3NotFound
from app.services.arena_v4_settlement import (
    resolve_appeal_settlement,
    result_from_score,
)


class ArenaV4AppealReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = ArenaV3Repository(db)

    def submit(
        self, *, review_id: int, admin_id: int, payload, idempotency_key: str
    ):
        review = self.repository.get_admin_review_for_update(review_id)
        if review is None or review.review_type != ArenaV4ReviewType.APPEAL:
            raise ArenaV3NotFound("Arena appeal review not found")
        if review.status == ArenaV4AdminReviewStatus.DECIDED:
            appeal = self.repository.get_appeal(review.match_id)
            if (
                review.idempotency_key == idempotency_key
                and review.assigned_admin_id == admin_id
                and review.reason == payload.reason
                and review.owner_score == payload.owner_score
                and review.opponent_score == payload.opponent_score
                and appeal is not None
                and appeal.resolution == payload.action.value
            ):
                self.db.rollback()
                return review
            raise ArenaV3Conflict("Arena appeal review is already resolved")
        if (
            review.status != ArenaV4AdminReviewStatus.CLAIMED
            or review.assigned_admin_id != admin_id
        ):
            raise ArenaV3Conflict("Admin must claim the appeal before resolving")

        match = self.repository.get_match_for_update(review.match_id)
        appeal = self.repository.get_appeal_for_update(review.match_id)
        if match is None or appeal is None:
            raise ArenaV3NotFound("Arena appeal match is missing")
        if match.status != ArenaV3Status.FINISHED:
            raise ArenaV3Conflict("Appeal review requires a finished match")
        if match.result_version != review.result_version:
            raise ArenaV3Conflict("Arena result changed after appeal was queued")
        if appeal.status not in {
            ArenaV3AppealStatus.PENDING,
            ArenaV3AppealStatus.UNDER_REVIEW,
        }:
            raise ArenaV3Conflict("Arena appeal is already resolved")

        if payload.action == ArenaV4AppealReviewAction.UPDATE_SCORE:
            decision = result_from_score(
                payload.owner_score, payload.opponent_score
            )
        elif payload.action == ArenaV4AppealReviewAction.CANCEL_MATCH:
            decision = ArenaV4ResultType.CANCEL
        else:
            decision = match.current_result_type

        review.status = ArenaV4AdminReviewStatus.DECIDED
        review.decision = decision
        review.owner_score = payload.owner_score
        review.opponent_score = payload.opponent_score
        review.reason = payload.reason
        review.idempotency_key = idempotency_key
        review.decided_at = datetime.now(timezone.utc)
        appeal.status = ArenaV3AppealStatus.RESOLVED
        appeal.admin_id = admin_id
        appeal.resolution = payload.action.value
        appeal.admin_comment = payload.reason
        appeal.resolved_at = review.decided_at
        try:
            resolve_appeal_settlement(
                self.db,
                repository=self.repository,
                match=match,
                review=review,
                appeal=appeal,
                action=payload.action,
                owner_score=payload.owner_score,
                opponent_score=payload.opponent_score,
                reason=payload.reason,
                now=review.decided_at,
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ArenaV3Conflict(
                "Appeal review idempotency key is already used"
            ) from exc
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(review)
        return review
