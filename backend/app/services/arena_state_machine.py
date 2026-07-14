from enum import Enum

from app.models.match import Match, MatchStatus


class ArenaTransitionError(ValueError):
    """Raised when an Arena action is invalid for the current match state."""


class ArenaAction(str, Enum):
    ACCEPT = "ACCEPT"
    START_READY_CHECK = "START_READY_CHECK"
    MARK_READY = "MARK_READY"
    FINISH_READY_CHECK = "FINISH_READY_CHECK"
    CREATE_ROOM_CODE = "CREATE_ROOM_CODE"
    UPLOAD_EVIDENCE = "UPLOAD_EVIDENCE"
    RESOLVE = "RESOLVE"
    PARTICIPANT_CANCEL = "PARTICIPANT_CANCEL"
    CANCEL = "CANCEL"


ALLOWED_ACTION_STATUSES = {
    ArenaAction.ACCEPT: {MatchStatus.WAITING_PLAYER},
    ArenaAction.START_READY_CHECK: {MatchStatus.WAITING_READY},
    ArenaAction.MARK_READY: {MatchStatus.WAITING_READY},
    ArenaAction.FINISH_READY_CHECK: {MatchStatus.WAITING_READY},
    ArenaAction.CREATE_ROOM_CODE: {MatchStatus.ROOM_READY},
    ArenaAction.UPLOAD_EVIDENCE: {MatchStatus.PLAYING},
    ArenaAction.RESOLVE: {
        MatchStatus.WAITING_ADMIN,
        MatchStatus.TECHNICAL_REVIEW,
    },
    ArenaAction.PARTICIPANT_CANCEL: {
        MatchStatus.WAITING_PLAYER,
        MatchStatus.WAITING_READY,
        MatchStatus.ROOM_READY,
        MatchStatus.ROOM_CREATED,
    },
    ArenaAction.CANCEL: {
        MatchStatus.WAITING_PLAYER,
        MatchStatus.WAITING_READY,
        MatchStatus.ROOM_READY,
        MatchStatus.ROOM_CREATED,
        MatchStatus.PLAYING,
        MatchStatus.TECHNICAL_REVIEW,
        MatchStatus.WAITING_ADMIN,
    },
}


def ensure_action_allowed(match: Match, action: ArenaAction) -> None:
    if match.status not in ALLOWED_ACTION_STATUSES[action]:
        status_value = getattr(match.status, "value", str(match.status))
        raise ArenaTransitionError(
            f"{action.value} action is not allowed from {status_value} status"
        )

    if action == ArenaAction.START_READY_CHECK and match.ready_check_started_at is not None:
        raise ArenaTransitionError("Ready check has already started")

    if action in {ArenaAction.MARK_READY, ArenaAction.FINISH_READY_CHECK}:
        if match.ready_check_started_at is None:
            raise ArenaTransitionError("Ready check has not started")


def ensure_ready_not_repeated(match: Match, telegram_id: int) -> None:
    ensure_action_allowed(match, ArenaAction.MARK_READY)
    if telegram_id == match.creator_telegram_id and match.creator_ready:
        raise ArenaTransitionError("Creator is already ready")
    if telegram_id == match.opponent_telegram_id and match.opponent_ready:
        raise ArenaTransitionError("Opponent is already ready")


def ensure_evidence_not_repeated(
    match: Match,
    telegram_id: int,
    *,
    screenshot_submitted: bool = True,
    video_submitted: bool = False,
) -> None:
    ensure_action_allowed(match, ArenaAction.UPLOAD_EVIDENCE)
    if telegram_id == match.creator_telegram_id:
        if screenshot_submitted and match.creator_result_screenshot:
            raise ArenaTransitionError("Creator screenshot has already been submitted")
        if video_submitted and match.creator_result_video:
            raise ArenaTransitionError("Creator video has already been submitted")
    elif telegram_id == match.opponent_telegram_id:
        if screenshot_submitted and match.opponent_result_screenshot:
            raise ArenaTransitionError("Opponent screenshot has already been submitted")
        if video_submitted and match.opponent_result_video:
            raise ArenaTransitionError("Opponent video has already been submitted")
