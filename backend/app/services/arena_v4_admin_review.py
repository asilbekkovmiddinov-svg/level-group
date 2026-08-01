from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.arena_v3 import (
    ArenaV4AdminReview,
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
from app.models.user import User
from app.services.object_storage import (
    StorageConfigurationError,
    StorageOperationError,
    generate_presigned_get_url,
)
from app.services.telegram_notifications import edit_arena_admin_post


class ArenaV4AdminReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.repository = ArenaV3Repository(db)

    def list_reviews(
        self, *, status=None, review_type=None, limit: int = 50, offset: int = 0
    ):
        return self.repository.list_admin_reviews(
            status=status, review_type=review_type, limit=limit, offset=offset
        )

    def submit_channel_decision(
        self, *, match_id: int, admin_id: int, payload, idempotency_key: str
    ):
        """Apply the channel score without exposing a review queue.

        The review row remains an immutable audit/decision record only.
        """
        match = self.repository.get_match_for_update(match_id)
        if match is None:
            raise ArenaV3NotFound("Arena V3 match not found")
        review = self.repository.get_initial_admin_review(match.id, match.result_version)
        if review is None:
            review = self.repository.add_admin_review(ArenaV4AdminReview(
                match_id=match.id,
                review_type=ArenaV4ReviewType.INITIAL,
                status=ArenaV4AdminReviewStatus.CLAIMED,
                result_version=match.result_version,
                expected_match_version=match.version,
                assigned_admin_id=admin_id,
                claimed_at=datetime.now(timezone.utc),
            ))
        elif review.status != ArenaV4AdminReviewStatus.DECIDED:
            review.status = ArenaV4AdminReviewStatus.CLAIMED
            review.assigned_admin_id = admin_id
            review.claimed_at = review.claimed_at or datetime.now(timezone.utc)
        self.db.flush()
        return self.submit_decision(
            review_id=review.id, admin_id=admin_id, payload=payload,
            idempotency_key=idempotency_key,
        )

    def submit_channel_cancel(
        self, *, match_id: int, admin_id: int, payload, idempotency_key: str
    ):
        match = self.repository.get_match_for_update(match_id)
        if match is None:
            raise ArenaV3NotFound("Arena V3 match not found")
        review = self.repository.get_initial_admin_review(match.id, match.result_version)
        if review is None:
            review = self.repository.add_admin_review(ArenaV4AdminReview(
                match_id=match.id, review_type=ArenaV4ReviewType.INITIAL,
                status=ArenaV4AdminReviewStatus.CLAIMED,
                result_version=match.result_version,
                expected_match_version=match.version,
                assigned_admin_id=admin_id, claimed_at=datetime.now(timezone.utc),
            ))
        elif review.status != ArenaV4AdminReviewStatus.DECIDED:
            review.status = ArenaV4AdminReviewStatus.CLAIMED
            review.assigned_admin_id = admin_id
        self.db.flush()
        return self.submit_cancel(
            review_id=review.id, admin_id=admin_id, payload=payload,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _profile(user, player_id):
        if user is None:
            return {
                "telegram_id": player_id,
                "display_name": f"Telegram user {player_id}",
                "username": None,
            }
        display_name = " ".join(
            value for value in (user.first_name, user.last_name) if value
        )
        return {
            "telegram_id": user.telegram_id,
            "display_name": (
                display_name or user.username or f"Telegram user {player_id}"
            ),
            "username": user.username,
        }

    @staticmethod
    def _media_url(storage_key):
        if not storage_key:
            return None
        try:
            return generate_presigned_get_url(storage_key)
        except (StorageConfigurationError, StorageOperationError):
            return None

    def detail(self, review_id: int):
        review = self.repository.get_admin_review(review_id)
        if review is None:
            raise ArenaV3NotFound("Arena admin review not found")
        match = self.repository.get_match(review.match_id)
        screenshots = self.repository.list_screenshots(review.match_id)
        screenshot_data = [
            {
                "id": item.id,
                "match_id": item.match_id,
                "player_id": item.player_id,
                "mime_type": item.mime_type,
                "file_size": item.file_size,
                "width": item.width,
                "height": item.height,
                "validation_status": item.validation_status,
                "uploaded_at": item.uploaded_at,
                "media_url": self._media_url(item.storage_key),
            }
            for item in screenshots
        ]
        appeal = (
            self.repository.get_appeal(review.match_id)
            if review.review_type == ArenaV4ReviewType.APPEAL
            else None
        )
        appeal_data = None
        if appeal is not None:
            appeal_data = {
                "id": appeal.id,
                "match_id": appeal.match_id,
                "submitted_by": appeal.submitted_by,
                "reason": appeal.reason,
                "status": appeal.status,
                "submitted_at": appeal.submitted_at,
                "deadline_at": appeal.deadline_at,
                "video_storage_key": appeal.video_storage_key,
                "video_url": self._media_url(appeal.video_storage_key),
                "file_hash": appeal.file_hash,
                "resolution": appeal.resolution,
                "admin_comment": appeal.admin_comment,
                "resolved_at": appeal.resolved_at,
            }
        return {
            "review": review,
            "match": match,
            "player_a": self._profile(
                self.db.get(User, match.owner_id), match.owner_id
            ),
            "player_b": self._profile(
                self.db.get(User, match.opponent_id), match.opponent_id
            ),
            "screenshots": screenshot_data,
            "appeal": appeal_data,
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
        if match.admin_channel_message_id:
            try:
                edit_arena_admin_post(
                    match.admin_channel_message_id,
                    "\n".join([
                        "✅ Match yakunlandi",
                        f"Hisob: {match.owner_score} : {match.opponent_score}",
                        f"Winner: {match.winner_id}", f"Admin: {admin_id}",
                        f"Tekshirilgan vaqt: {review.decided_at.isoformat()}",
                    ]),
                )
            except Exception:
                pass
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
