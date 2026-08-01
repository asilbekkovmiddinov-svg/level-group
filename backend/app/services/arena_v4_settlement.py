from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.crud.transaction import create_transaction
from app.crud.wallet import (
    add_locked_reward_efc,
    confirm_locked_efc,
    unlock_efc_balance,
)
from app.models.arena_v3 import (
    ArenaV3MatchEvent,
    ArenaV3SettlementStatus,
    ArenaV3Stats,
    ArenaV3Status,
    ArenaV4ResultRevision,
    ArenaV4ResultType,
    ArenaV4RewardHoldStatus,
    ArenaV4SettlementOperation,
    ArenaV4SettlementOperationStatus,
)
from app.repositories.arena_v3 import ArenaV3Repository
from app.services.arena_v3 import ArenaV3Conflict
from app.services.arena_v3_state_machine import transition_arena_v3


FEE_PERCENT = Decimal("10")
REWARD_HOLD_MINUTES = 30
CENT = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


def _wallet_transaction(
    db, *, player_id: int, amount: Decimal, balance_before: Decimal,
    balance_after: Decimal, kind: str, description: str, status: str = "SUCCESS",
):
    transaction = create_transaction(
        db=db,
        telegram_id=player_id,
        currency="EFC",
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        type=kind,
        description=description,
        commit=False,
    )
    transaction.status = status
    return transaction


def _operation(
    repository, *, match, result_version: int, player_id: int | None,
    operation_type: str, amount: Decimal, wallet_transaction_id: int | None,
    metadata: dict | None = None,
):
    return repository.add_settlement_operation(ArenaV4SettlementOperation(
        match_id=match.id,
        result_version=result_version,
        player_id=player_id,
        operation_type=operation_type,
        amount_efc=amount,
        status=ArenaV4SettlementOperationStatus.COMPLETED,
        wallet_transaction_id=wallet_transaction_id,
        idempotency_key=(
            f"arena-v4:{match.id}:{result_version}:"
            f"{operation_type}:{player_id or 'platform'}"
        ),
        operation_metadata=metadata,
        completed_at=datetime.now(timezone.utc),
    ))


def _consume_stake(db, repository, match, player_id, result_version):
    wallet = confirm_locked_efc(db, player_id, match.stake_efc)
    if wallet is None:
        raise ArenaV3Conflict("Arena V4 locked stake is unavailable")
    amount = _money(match.stake_efc)
    transaction = _wallet_transaction(
        db,
        player_id=player_id,
        amount=amount,
        balance_before=_money(wallet.efc_balance),
        balance_after=_money(wallet.efc_balance),
        kind="ARENA_V4_STAKE_SPENT",
        description=f"Arena V4 match #{match.id} stake settled",
    )
    _operation(
        repository,
        match=match,
        result_version=result_version,
        player_id=player_id,
        operation_type="STAKE_CONSUME",
        amount=amount,
        wallet_transaction_id=transaction.id,
    )


def _refund_stake(db, repository, match, player_id, result_version):
    wallet = unlock_efc_balance(db, player_id, match.stake_efc)
    if wallet is None:
        raise ArenaV3Conflict("Arena V4 locked stake is unavailable")
    amount = _money(match.stake_efc)
    transaction = _wallet_transaction(
        db,
        player_id=player_id,
        amount=amount,
        balance_before=_money(wallet.efc_balance) - amount,
        balance_after=_money(wallet.efc_balance),
        kind="ARENA_V4_REFUND",
        description=f"Arena V4 match #{match.id} stake refunded",
    )
    _operation(
        repository,
        match=match,
        result_version=result_version,
        player_id=player_id,
        operation_type="STAKE_REFUND",
        amount=amount,
        wallet_transaction_id=transaction.id,
    )


def _lock_reward(db, repository, match, winner_id, amount, result_version):
    wallet = add_locked_reward_efc(db, winner_id, amount)
    if wallet is None:
        raise ArenaV3Conflict("Arena V4 locked reward could not be credited")
    available = _money(wallet.efc_balance)
    transaction = _wallet_transaction(
        db,
        player_id=winner_id,
        amount=amount,
        balance_before=available,
        balance_after=available,
        kind="ARENA_V4_REWARD_LOCKED",
        description=f"Arena V4 match #{match.id} winner reward locked",
        status="LOCKED",
    )
    _operation(
        repository,
        match=match,
        result_version=result_version,
        player_id=winner_id,
        operation_type="REWARD_LOCK",
        amount=amount,
        wallet_transaction_id=transaction.id,
        metadata={"release_at": match.reward_release_at.isoformat()},
    )


def _stats(repository, player_id):
    value = repository.get_stats_for_update(player_id)
    return value or repository.add_stats(ArenaV3Stats(player_id=player_id))


def _update_competitive_stats(repository, match, decision):
    owner = _stats(repository, match.owner_id)
    opponent = _stats(repository, match.opponent_id)
    owner_score = match.owner_score or 0
    opponent_score = match.opponent_score or 0
    for value in (owner, opponent):
        value.total_matches += 1
    owner.goals_for += owner_score
    owner.goals_against += opponent_score
    opponent.goals_for += opponent_score
    opponent.goals_against += owner_score
    if decision == ArenaV4ResultType.DRAW:
        owner.draws += 1
        opponent.draws += 1
        owner.current_streak = 0
        opponent.current_streak = 0
    else:
        winner, loser = (
            (owner, opponent)
            if decision == ArenaV4ResultType.PLAYER_A_WIN
            else (opponent, owner)
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
        ).quantize(CENT)


def apply_admin_settlement(db, *, repository, match, review, payload, now=None):
    if match.opponent_id is None:
        raise ArenaV3Conflict("Arena V4 opponent is missing")
    if match.settlement_status != ArenaV3SettlementStatus.NOT_STARTED:
        raise ArenaV3Conflict("Arena V4 match is already settled")

    now = now or datetime.now(timezone.utc)
    result_version = match.result_version + 1
    decision = payload.decision
    stake = _money(match.stake_efc)
    total_pool = _money(stake * Decimal("2"))
    match.total_pool_efc = total_pool
    match.owner_score = payload.owner_score
    match.opponent_score = payload.opponent_score
    match.current_result_type = decision
    match.result_version = result_version
    match.current_decision_id = review.id
    if match.initial_decision_id is None:
        match.initial_decision_id = review.id
    match.result_source = "ADMIN"
    match.appeal_deadline_at = now + timedelta(minutes=REWARD_HOLD_MINUTES)
    match.has_appeal = False
    match.settlement_status = ArenaV3SettlementStatus.PENDING

    winner_id = None
    if decision in {
        ArenaV4ResultType.PLAYER_A_WIN,
        ArenaV4ResultType.PLAYER_B_WIN,
    }:
        commission = _money(total_pool * FEE_PERCENT / Decimal("100"))
        reward = _money(total_pool - commission)
        match.commission_efc = commission
        match.winner_reward_efc = reward
        winner_id = (
            match.owner_id
            if decision == ArenaV4ResultType.PLAYER_A_WIN
            else match.opponent_id
        )
        loser_id = (
            match.opponent_id if winner_id == match.owner_id else match.owner_id
        )
        match.winner_id = winner_id
        match.loser_id = loser_id
        match.reward_hold_status = ArenaV4RewardHoldStatus.LOCKED
        match.reward_release_at = now + timedelta(minutes=REWARD_HOLD_MINUTES)
        _consume_stake(db, repository, match, match.owner_id, result_version)
        _consume_stake(db, repository, match, match.opponent_id, result_version)
        _lock_reward(db, repository, match, winner_id, reward, result_version)
        _operation(
            repository,
            match=match,
            result_version=result_version,
            player_id=None,
            operation_type="PLATFORM_FEE",
            amount=commission,
            wallet_transaction_id=None,
            metadata={"fee_percent": str(FEE_PERCENT)},
        )
        match.settlement_status = ArenaV3SettlementStatus.COMPLETED
    else:
        match.commission_efc = Decimal("0.00")
        match.winner_reward_efc = Decimal("0.00")
        match.winner_id = None
        match.loser_id = None
        match.reward_hold_status = ArenaV4RewardHoldStatus.NONE
        match.reward_release_at = None
        _refund_stake(db, repository, match, match.owner_id, result_version)
        _refund_stake(db, repository, match, match.opponent_id, result_version)
        _operation(
            repository,
            match=match,
            result_version=result_version,
            player_id=None,
            operation_type="PLATFORM_FEE",
            amount=Decimal("0.00"),
            wallet_transaction_id=None,
            metadata={"fee_percent": "0"},
        )
        match.settlement_status = ArenaV3SettlementStatus.REFUNDED

    if decision != ArenaV4ResultType.CANCEL:
        _update_competitive_stats(repository, match, decision)
    else:
        match.cancel_reason = "ADMIN_CANCEL"

    repository.add_result_revision(ArenaV4ResultRevision(
        match_id=match.id,
        version=result_version,
        review_id=review.id,
        previous_result_type=None,
        new_result_type=decision.value,
        previous_winner_id=None,
        new_winner_id=winner_id,
        new_owner_score=payload.owner_score,
        new_opponent_score=payload.opponent_score,
        new_reward_efc=match.winner_reward_efc,
        new_fee_efc=match.commission_efc,
        admin_id=review.assigned_admin_id,
        reason=payload.reason or "INITIAL_ADMIN_DECISION",
    ))
    transition_arena_v3(match, ArenaV3Status.FINISHED)
    match.settled_at = now
    match.finished_at = now
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type="ADMIN_SETTLEMENT_COMPLETED",
        from_status=ArenaV3Status.WAITING_ADMIN.value,
        to_status=ArenaV3Status.FINISHED.value,
        actor_type="ADMIN",
        actor_id=review.assigned_admin_id,
        idempotency_key=f"admin-settlement:{review.id}",
        event_metadata={
            "decision": decision.value,
            "result_version": result_version,
        },
    ))
