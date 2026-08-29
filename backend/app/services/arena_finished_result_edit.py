from datetime import datetime, timezone
from decimal import Decimal

from app.models.arena_v3 import (
    ArenaV3MatchEvent,
    ArenaV3SettlementStatus,
    ArenaV3Status,
    ArenaV4ResultRevision,
    ArenaV4ResultType,
    ArenaV4RewardHoldStatus,
)
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3NotFound
from app.services.arena_v4_settlement import (
    _recalculate_player_stats,
    result_from_score,
)


def revise_finished_ticket_result(
    db, *, repository, match_id: int, admin_id: int,
    owner_score: int, opponent_score: int, reason: str,
):
    """Correct a finished ticket Arena result without replaying settlement.

    Arena V5 STANDARD matches settle only rating/statistics, so correction is
    authoritative by replacing the current score/winner and rebuilding both
    players' stats from finished matches. A result revision and event preserve
    the complete audit trail.
    """
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    if match.status != ArenaV3Status.FINISHED:
        raise ArenaV3Conflict("Only a finished Arena match can be corrected")
    if match.match_type != "STANDARD" or match.ticket_cost <= 0:
        raise ArenaV3Conflict("Finished-result correction is only enabled for ticket Arena")
    if match.opponent_id is None:
        raise ArenaV3Conflict("Arena opponent is missing")

    new_result = result_from_score(
        owner_score, opponent_score, allow_draw=match.flow_version >= 5
    )
    if (
        match.owner_score == owner_score
        and match.opponent_score == opponent_score
        and match.current_result_type == new_result
    ):
        raise ArenaV3Conflict("Updated score must differ from current score")

    old_version = match.result_version
    old_result = match.current_result_type
    old_winner_id = match.winner_id
    old_owner_score = match.owner_score
    old_opponent_score = match.opponent_score
    new_version = old_version + 1

    match.owner_score = owner_score
    match.opponent_score = opponent_score
    match.current_result_type = new_result
    match.result_version = new_version
    match.result_source = "ADMIN_CORRECTION"
    match.cancel_reason = None
    match.stake_efc = Decimal("0.00")
    match.total_pool_efc = Decimal("0.00")
    match.commission_efc = Decimal("0.00")
    match.winner_reward_efc = Decimal("0.00")
    match.reward_hold_status = ArenaV4RewardHoldStatus.NONE
    match.reward_release_at = None
    match.settlement_status = ArenaV3SettlementStatus.COMPLETED

    if new_result == ArenaV4ResultType.PLAYER_A_WIN:
        match.winner_id = match.owner_id
        match.loser_id = match.opponent_id
    elif new_result == ArenaV4ResultType.PLAYER_B_WIN:
        match.winner_id = match.opponent_id
        match.loser_id = match.owner_id
    else:
        match.winner_id = None
        match.loser_id = None

    repository.add_result_revision(ArenaV4ResultRevision(
        match_id=match.id,
        version=new_version,
        review_id=None,
        previous_result_type=old_result.value if old_result else None,
        new_result_type=new_result.value,
        previous_winner_id=old_winner_id,
        new_winner_id=match.winner_id,
        previous_owner_score=old_owner_score,
        previous_opponent_score=old_opponent_score,
        new_owner_score=owner_score,
        new_opponent_score=opponent_score,
        previous_reward_efc=Decimal("0.00"),
        new_reward_efc=Decimal("0.00"),
        previous_fee_efc=Decimal("0.00"),
        new_fee_efc=Decimal("0.00"),
        admin_id=admin_id,
        reason=reason or "ADMIN_FINISHED_RESULT_CORRECTION",
    ))

    _recalculate_player_stats(repository, match.owner_id)
    _recalculate_player_stats(repository, match.opponent_id)

    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type="ADMIN_FINISHED_RESULT_CORRECTED",
        from_status=ArenaV3Status.FINISHED.value,
        to_status=ArenaV3Status.FINISHED.value,
        actor_type="ADMIN",
        actor_id=admin_id,
        idempotency_key=f"finished-result-correction:{match.id}:{new_version}",
        event_metadata={
            "old_result_version": old_version,
            "new_result_version": new_version,
            "old_score": [old_owner_score, old_opponent_score],
            "new_score": [owner_score, opponent_score],
            "old_winner_id": old_winner_id,
            "new_winner_id": match.winner_id,
        },
    ))
    match.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(match)
    return match
