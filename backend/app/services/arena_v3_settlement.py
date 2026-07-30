from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from app.core import config
from app.crud.transaction import create_transaction
from app.crud.wallet import (
    add_efc_balance,
    confirm_locked_efc,
    lock_efc_balance,
    unlock_efc_balance,
)
from app.models.arena_v3 import (
    ArenaV3AIReviewStatus,
    ArenaV3Appeal,
    ArenaV3AppealStatus,
    ArenaV3Match,
    ArenaV3MatchEvent,
    ArenaV3NotificationDelivery,
    ArenaV3SettlementStatus,
    ArenaV3Stats,
    ArenaV3Status,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3NotFound,
    ArenaV3Unavailable,
)
from app.services.arena_v3_state_machine import transition_arena_v3


def _money(value) -> Decimal:
    return Decimal(str(value))


def _wallet_transaction(db, player_id, amount, wallet, kind, description, before):
    create_transaction(
        db=db,
        telegram_id=player_id,
        currency="EFC",
        amount=_money(amount),
        balance_before=_money(before),
        balance_after=_money(wallet.efc_balance),
        type=kind,
        description=description,
        commit=False,
    )


def lock_match_stake(db, player_id: int, amount, match_id: int) -> None:
    wallet = lock_efc_balance(db, player_id, amount)
    if wallet is None:
        raise ArenaV3Conflict("EFC balance is insufficient")
    value = _money(amount)
    _wallet_transaction(
        db, player_id, value, wallet, "ARENA_V3_LOCK",
        f"Arena V3 match #{match_id} stake locked",
        _money(wallet.efc_balance) + value,
    )


def _consume_stake(db, player_id: int, amount, match_id: int):
    wallet = confirm_locked_efc(db, player_id, amount)
    if wallet is None:
        raise ArenaV3Conflict("Arena V3 locked stake is unavailable")
    _wallet_transaction(
        db, player_id, amount, wallet, "ARENA_V3_STAKE_SPENT",
        f"Arena V3 match #{match_id} stake settled",
        wallet.efc_balance,
    )


def _reward(db, player_id: int, amount, match_id: int):
    wallet = add_efc_balance(db, player_id, amount)
    if wallet is None:
        raise ArenaV3Conflict("Arena V3 winner reward could not be credited")
    value = _money(amount)
    _wallet_transaction(
        db, player_id, value, wallet, "ARENA_V3_REWARD",
        f"Arena V3 match #{match_id} winner reward",
        _money(wallet.efc_balance) - value,
    )


def _unlock(db, player_id: int, amount, match_id: int):
    wallet = unlock_efc_balance(db, player_id, amount)
    if wallet is None:
        raise ArenaV3Conflict("Arena V3 locked stake is unavailable")
    value = _money(amount)
    _wallet_transaction(
        db, player_id, value, wallet, "ARENA_V3_REFUND",
        f"Arena V3 match #{match_id} stake refunded",
        _money(wallet.efc_balance) - value,
    )


def _event(repository, match, event_type, key, metadata=None):
    if repository.get_event_by_idempotency(match.id, key):
        return
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type=event_type,
        from_status=ArenaV3Status.AI_REVIEW.value,
        to_status=ArenaV3Status(match.status).value,
        actor_type="SYSTEM",
        actor_id=None,
        idempotency_key=key,
        event_metadata=metadata,
    ))


def _notification(repository, match, player_id, event_type):
    if player_id is None:
        return
    key = f"arena-v3:{match.id}:{event_type}:{player_id}"
    if repository.get_notification_by_dedup(key):
        return
    repository.add_notification(ArenaV3NotificationDelivery(
        match_id=match.id,
        recipient_id=player_id,
        event_type=event_type,
        dedup_key=key,
        status="PENDING",
    ))


def _stats(repository, player_id):
    value = repository.get_stats_for_update(player_id)
    return value or repository.add_stats(ArenaV3Stats(player_id=player_id))


def _update_stats(repository, match, winner_id):
    owner = _stats(repository, match.owner_id)
    opponent = _stats(repository, match.opponent_id)
    owner.total_matches += 1
    opponent.total_matches += 1
    owner.goals_for += match.owner_score
    owner.goals_against += match.opponent_score
    opponent.goals_for += match.opponent_score
    opponent.goals_against += match.owner_score
    if winner_id is None:
        owner.draws += 1
        opponent.draws += 1
        owner.current_streak = 0
        opponent.current_streak = 0
    else:
        winner, loser = (
            (owner, opponent) if winner_id == match.owner_id else (opponent, owner)
        )
        winner.wins += 1
        loser.losses += 1
        winner.current_streak += 1
        winner.best_streak = max(winner.best_streak, winner.current_streak)
        loser.current_streak = 0
        winner.total_efc_won += _money(match.winner_reward_efc) - _money(match.stake_efc)
        loser.total_efc_lost += _money(match.stake_efc)
    for value in (owner, opponent):
        value.win_rate = (
            Decimal(value.wins) * Decimal("100") / Decimal(value.total_matches)
        ).quantize(Decimal("0.01"))


def settle_completed_match(db, match_id: int):
    if not config.ARENA_V3_SETTLEMENT_ENABLED:
        raise ArenaV3Unavailable("Arena V3 settlement is disabled")
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    if match.settlement_status == ArenaV3SettlementStatus.COMPLETED:
        return match
    if match.settlement_status == ArenaV3SettlementStatus.REFUNDED:
        raise ArenaV3Conflict("Arena V3 match was already refunded")
    review = repository.get_latest_ai_review(match.id)
    if review is None or review.status != ArenaV3AIReviewStatus.COMPLETED:
        raise ArenaV3Conflict("Completed Arena V3 AI result is required")
    if match.status != ArenaV3Status.AI_REVIEW:
        raise ArenaV3Conflict("Arena V3 match is not awaiting settlement")
    if match.opponent_id is None:
        raise ArenaV3Conflict("Arena V3 opponent is missing")

    match.settlement_status = ArenaV3SettlementStatus.PENDING
    match.owner_score = review.detected_owner_score
    match.opponent_score = review.detected_opponent_score
    match.winner_id = review.winner_player_id
    match.provisional_winner_id = review.winner_player_id
    match.result_source = "AI"
    if review.winner_player_id is None:
        _unlock(db, match.owner_id, match.stake_efc, match.id)
        _unlock(db, match.opponent_id, match.stake_efc, match.id)
        match.settlement_status = ArenaV3SettlementStatus.REFUNDED
    else:
        loser_id = (
            match.opponent_id
            if review.winner_player_id == match.owner_id
            else match.owner_id
        )
        match.loser_id = loser_id
        _consume_stake(db, match.owner_id, match.stake_efc, match.id)
        _consume_stake(db, match.opponent_id, match.stake_efc, match.id)
        _reward(db, review.winner_player_id, match.winner_reward_efc, match.id)
        match.settlement_status = ArenaV3SettlementStatus.COMPLETED

    transition_arena_v3(match, ArenaV3Status.FINISHED)
    now = datetime.now(timezone.utc)
    match.settled_at = now
    match.finished_at = now
    _update_stats(repository, match, review.winner_player_id)
    _event(repository, match, "MATCH_FINISHED", "settlement:finished", {
        "winner_id": review.winner_player_id,
        "score": review.score,
    })
    _notification(repository, match, match.owner_id, "MATCH_FINISHED")
    _notification(repository, match, match.opponent_id, "MATCH_FINISHED")
    if review.winner_player_id is not None:
        _notification(repository, match, review.winner_player_id, "MATCH_WON")
        _notification(repository, match, match.loser_id, "MATCH_LOST")
    db.commit()
    db.refresh(match)
    return match


def refund_match(db, match_id: int, *, reason: str, preserve_status=False):
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    if match.settlement_status == ArenaV3SettlementStatus.REFUNDED:
        return match
    if match.settlement_status == ArenaV3SettlementStatus.COMPLETED:
        raise ArenaV3Conflict("Completed Arena V3 settlement cannot be refunded")
    _unlock(db, match.owner_id, match.stake_efc, match.id)
    if match.opponent_id is not None:
        _unlock(db, match.opponent_id, match.stake_efc, match.id)
    match.settlement_status = ArenaV3SettlementStatus.REFUNDED
    match.settled_at = datetime.now(timezone.utc)
    match.cancel_reason = reason
    _event(repository, match, "REFUND_COMPLETED", "settlement:refund", {
        "reason": reason,
    })
    _notification(repository, match, match.owner_id, "REFUND_COMPLETED")
    _notification(repository, match, match.opponent_id, "REFUND_COMPLETED")
    db.commit()
    db.refresh(match)
    return match


def open_ai_appeal(db, match_id: int):
    repository = ArenaV3Repository(db)
    match = repository.get_match_for_update(match_id)
    if match is None:
        raise ArenaV3NotFound("Arena V3 match not found")
    review = repository.get_latest_ai_review(match.id)
    if review is None or review.status != ArenaV3AIReviewStatus.APPEAL_REQUIRED:
        raise ArenaV3Conflict("Arena V3 appeal-required AI result is missing")
    appeal = repository.get_open_appeal(match.id)
    if appeal is None:
        appeal = repository.add_appeal(ArenaV3Appeal(
            match_id=match.id,
            submitted_by=None,
            reason_code="AI_SCREENSHOT_CONFLICT",
            status=ArenaV3AppealStatus.OPEN,
        ))
    _event(repository, match, "APPEAL_REQUIRED", "appeal:ai-conflict", {
        "appeal_id": appeal.id,
    })
    _notification(repository, match, match.owner_id, "APPEAL_REQUIRED")
    _notification(repository, match, match.opponent_id, "APPEAL_REQUIRED")
    db.commit()
    db.refresh(appeal)
    return appeal


def handle_ai_outcome(db, match_id: int):
    repository = ArenaV3Repository(db)
    review = repository.get_latest_ai_review(match_id)
    if review is None:
        return None
    if review.status == ArenaV3AIReviewStatus.COMPLETED:
        return settle_completed_match(db, match_id)
    if review.status == ArenaV3AIReviewStatus.APPEAL_REQUIRED:
        return open_ai_appeal(db, match_id)
    if (
        review.status == ArenaV3AIReviewStatus.FAILED
        and config.ARENA_V3_REFUND_ON_AI_FAILURE
    ):
        return refund_match(
            db, match_id, reason="AI_PROCESSING_FAILED", preserve_status=True
        )
    return review


def run_ai_outcome_queue(db, *, limit: int = 50):
    repository = ArenaV3Repository(db)
    match_ids = [
        row[0] for row in (
            db.query(ArenaV3Match.id)
            .filter(ArenaV3Match.status == ArenaV3Status.AI_REVIEW)
            .order_by(
                ArenaV3Match.ai_review_started_at,
                ArenaV3Match.id,
            )
            .limit(limit).all()
        )
    ]
    processed = []
    for match_id in match_ids:
        review = repository.get_latest_ai_review(match_id)
        should_process = (
            review is not None
            and (
                review.status == ArenaV3AIReviewStatus.APPEAL_REQUIRED
                or (
                    review.status == ArenaV3AIReviewStatus.COMPLETED
                    and config.ARENA_V3_SETTLEMENT_ENABLED
                )
                or (
                    review.status == ArenaV3AIReviewStatus.FAILED
                    and config.ARENA_V3_REFUND_ON_AI_FAILURE
                )
            )
        )
        if should_process:
            processed.append(handle_ai_outcome(db, match_id))
    return processed
