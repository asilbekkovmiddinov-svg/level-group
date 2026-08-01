from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.arena_v3 import (
    ArenaV3AppealStatus,
    ArenaV3Status,
    ArenaV4AdminReviewStatus,
    ArenaV4ResultType,
    ArenaV4ReviewType,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3NotFound,
)
from app.services.arena_v4_settlement import (
    apply_admin_settlement,
    result_from_score,
)


class ArenaV4AdminReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = ArenaV3Repository(db)

    def list_reviews(self, *, status=None, limit: int = 50, offset: int = 0):
        return self.repository.list_admin_reviews(
            status=status, limit=limit, offset=offset
        )

    def detail(self, review_id: int):
        review = self.repository.get_admin_review(review_id)
        if review is None:
            raise ArenaV3NotFound("Arena admin review not found")
        match = self.repository.get_match(review.match_id)
        return {
            "review": review,
            "match": match,
            "screenshots": self.repository.list_screenshots(review.match_id),
            "appeal": (
                self.repository.get_appeal(review.match_id)
                if review.review_type == ArenaV4ReviewType.APPEAL
                else None
            ),
        }

    def claim(self, *, review_id: int, admin_id: int):
        review = self.repository.get_admin_review_for_update(review_id)
        if review is None:
            raise ArenaV3NotFound("Arena admin review not found")
        if review.status == ArenaV4AdminReviewStatus.CLAIMED:
            if review.assigned_admin_id == admin_id:
                self.db.rollback()
                return review
            raise ArenaV3Conflict("Arena admin review is already claimed")
        if review.status == ArenaV4AdminReviewStatus.DECIDED:
            raise ArenaV3Conflict("Arena admin review is already decided")

        review.status = ArenaV4AdminReviewStatus.CLAIMED
        review.assigned_admin_id = admin_id
        review.claimed_at = datetime.now(timezone.utc)
        if review.review_type == ArenaV4ReviewType.APPEAL:
            appeal = self.repository.get_appeal_for_update(review.match_id)
            if appeal is None:
                raise ArenaV3Conflict("Arena appeal is missing")
            appeal.status = ArenaV3AppealStatus.UNDER_REVIEW
            appeal.admin_id = admin_id
        self.db.commit()
        self.db.refresh(review)
        return review

    def submit_decision(
        self, *, review_id: int, admin_id: int, payload, idempotency_key: str
    ):
        review = self.repository.get_admin_review_for_update(review_id)
        if review is None:
            raise ArenaV3NotFound("Arena admin review not found")
        decision = result_from_score(payload.owner_score, payload.opponent_score)
        if review.status == ArenaV4AdminReviewStatus.DECIDED:
            if (
                review.idempotency_key == idempotency_key
                and review.assigned_admin_id == admin_id
                and review.decision == decision
                and review.owner_score == payload.owner_score
                and review.opponent_score == payload.opponent_score
                and review.reason == payload.reason
            ):
                self.db.rollback()
                return review
            raise ArenaV3Conflict("Arena admin decision is already final")
        if (
            review.status != ArenaV4AdminReviewStatus.CLAIMED
            or review.assigned_admin_id != admin_id
        ):
            raise ArenaV3Conflict("Admin must claim the review before deciding")

        match = self.repository.get_match_for_update(review.match_id)
        if match is None:
            raise ArenaV3NotFound("Arena V3 match not found")
        if match.status != ArenaV3Status.WAITING_ADMIN:
            raise ArenaV3Conflict("Arena match is not waiting for admin")
        if (
            review.expected_match_version is not None
            and match.version != review.expected_match_version
        ):
            raise ArenaV3Conflict("Arena match changed after review was queued")
        review.status = ArenaV4AdminReviewStatus.DECIDED
        review.decision = decision
        review.owner_score = payload.owner_score
        review.opponent_score = payload.opponent_score
        review.reason = payload.reason
        review.idempotency_key = idempotency_key
        review.decided_at = datetime.now(timezone.utc)
        try:
            apply_admin_settlement(
                self.db,
                repository=self.repository,
                match=match,
                review=review,
                payload=payload,
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ArenaV3Conflict("Admin decision idempotency key is already used") from exc
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(review)
        return review

    def submit_cancel(
        self, *, review_id: int, admin_id: int, payload, idempotency_key: str
    ):
        review = self.repository.get_admin_review_for_update(review_id)
        if review is None:
            raise ArenaV3NotFound("Arena admin review not found")
        if review.status == ArenaV4AdminReviewStatus.DECIDED:
            if (
                review.idempotency_key == idempotency_key
                and review.assigned_admin_id == admin_id
                and review.decision == ArenaV4ResultType.CANCEL
                and review.reason == payload.reason
            ):
                self.db.rollback()
                return review
            raise ArenaV3Conflict("Arena admin decision is already final")
        if (
            review.status != ArenaV4AdminReviewStatus.CLAIMED
            or review.assigned_admin_id != admin_id
        ):
            raise ArenaV3Conflict("Admin must claim the review before deciding")
        match = self.repository.get_match_for_update(review.match_id)
        if match is None:
            raise ArenaV3NotFound("Arena V3 match not found")
        if match.status != ArenaV3Status.WAITING_ADMIN:
            raise ArenaV3Conflict("Arena match is not waiting for admin")
        if (
            review.expected_match_version is not None
            and match.version != review.expected_match_version
        ):
            raise ArenaV3Conflict("Arena match changed after review was queued")
        review.status = ArenaV4AdminReviewStatus.DECIDED
        review.decision = ArenaV4ResultType.CANCEL
        review.reason = payload.reason
        review.idempotency_key = idempotency_key
        review.decided_at = datetime.now(timezone.utc)
        try:
            apply_admin_settlement(
                self.db,
                repository=self.repository,
                match=match,
                review=review,
                payload=payload,
                decision=ArenaV4ResultType.CANCEL,
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ArenaV3Conflict(
                "Admin decision idempotency key is already used"
            ) from exc
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(review)
        return review
