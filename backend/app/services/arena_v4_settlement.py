from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.crud.transaction import create_transaction
from app.crud.wallet import (
    add_locked_reward_efc,
    confirm_locked_efc,
    release_locked_reward_efc,
    remove_locked_reward_efc,
    restore_locked_stake_efc,
    reverse_refund_to_locked_efc,
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
from app.services.arena_v3_notifications import queue_v4_notification


FEE_PERCENT = Decimal("10")
REWARD_HOLD_MINUTES = 30
CENT = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT)


def result_from_score(owner_score: int, opponent_score: int) -> ArenaV4ResultType:
    if owner_score > opponent_score:
        return ArenaV4ResultType.PLAYER_A_WIN
    if opponent_score > owner_score:
        return ArenaV4ResultType.PLAYER_B_WIN
    raise ArenaV3Conflict("Equal scores are not allowed; penalty shootout is mandatory")


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
    metadata: dict | None = None, reverses_operation_id: int | None = None,
):
    return repository.add_settlement_operation(ArenaV4SettlementOperation(
        match_id=match.id,
        result_version=result_version,
        player_id=player_id,
        operation_type=operation_type,
        amount_efc=amount,
        status=ArenaV4SettlementOperationStatus.COMPLETED,
        wallet_transaction_id=wallet_transaction_id,
        reverses_operation_id=reverses_operation_id,
        idempotency_key=(
            f"arena-v4:{match.id}:{result_version}:"
            f"{operation_type}:{player_id or 'platform'}"
        ),
        operation_metadata=metadata,
        completed_at=datetime.now(timezone.utc),
    ))


def _queue_initial_result_notifications(repository, match, decision):
    if decision == ArenaV4ResultType.DRAW:
        events = ((match.owner_id, "MATCH_DRAW"), (match.opponent_id, "MATCH_DRAW"))
    elif decision == ArenaV4ResultType.CANCEL:
        events = (
            (match.owner_id, "MATCH_CANCELLED"),
            (match.opponent_id, "MATCH_CANCELLED"),
        )
    else:
        events = ((match.winner_id, "MATCH_WON"), (match.loser_id, "MATCH_LOST"))
    for player_id, event_type in events:
        queue_v4_notification(
            repository,
            match_id=match.id,
            recipient_id=player_id,
            event_type=event_type,
            dedup_key=(
                f"arena-v4:{match.id}:{match.result_version}:"
                f"{event_type}:{player_id}"
            ),
        )


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


def _lock_refund(db, repository, match, player_id, result_version):
    consumed = confirm_locked_efc(db, player_id, match.stake_efc)
    if consumed is None:
        raise ArenaV3Conflict("Arena V4 locked stake is unavailable")
    amount = _money(match.stake_efc)
    wallet = add_locked_reward_efc(db, player_id, amount)
    if wallet is None:
        raise ArenaV3Conflict("Arena V4 refund could not be locked")
    transaction = _wallet_transaction(
        db,
        player_id=player_id,
        amount=amount,
        balance_before=_money(wallet.efc_balance),
        balance_after=_money(wallet.efc_balance),
        kind="ARENA_V4_REFUND_LOCKED",
        description=f"Arena V4 match #{match.id} refund locked",
        status="LOCKED",
    )
    _operation(
        repository,
        match=match,
        result_version=result_version,
        player_id=player_id,
        operation_type="STAKE_REFUND",
        amount=amount,
        wallet_transaction_id=transaction.id,
        metadata={"locked": True, "release_at": match.reward_release_at.isoformat()},
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


def _recalculate_player_stats(repository, player_id: int):
    stats = _stats(repository, player_id)
    stats.total_matches = 0
    stats.wins = 0
    stats.losses = 0
    stats.draws = 0
    stats.goals_for = 0
    stats.goals_against = 0
    stats.win_rate = Decimal("0.00")
    stats.total_efc_won = Decimal("0.00")
    stats.total_efc_lost = Decimal("0.00")
    stats.current_streak = 0
    stats.best_streak = 0
    for item in repository.list_finished_matches_for_player(player_id):
        if item.current_result_type in {None, ArenaV4ResultType.CANCEL}:
            continue
        is_owner = item.owner_id == player_id
        own_score = item.owner_score if is_owner else item.opponent_score
        other_score = item.opponent_score if is_owner else item.owner_score
        stats.total_matches += 1
        stats.goals_for += own_score or 0
        stats.goals_against += other_score or 0
        if item.current_result_type == ArenaV4ResultType.DRAW:
            stats.draws += 1
            stats.current_streak = 0
        elif item.winner_id == player_id:
            stats.wins += 1
            stats.current_streak += 1
            stats.best_streak = max(stats.best_streak, stats.current_streak)
            stats.total_efc_won += (
                _money(item.winner_reward_efc) - _money(item.stake_efc)
            )
        else:
            stats.losses += 1
            stats.current_streak = 0
            stats.total_efc_lost += _money(item.stake_efc)
    if stats.total_matches:
        stats.win_rate = (
            Decimal(stats.wins) * Decimal("100") / Decimal(stats.total_matches)
        ).quantize(CENT)


def _rollback_wallet_settlement(
    db, repository, match, *, old_version: int, new_version: int
):
    operations = repository.list_settlement_operations_for_update(
        match.id, old_version
    )
    for operation in operations:
        if operation.status == ArenaV4SettlementOperationStatus.REVERSED:
            raise ArenaV3Conflict("Arena V4 settlement is already reversed")
        amount = _money(operation.amount_efc)
        transaction = None
        if operation.operation_type == "REWARD_LOCK":
            wallet = remove_locked_reward_efc(db, operation.player_id, amount)
            if wallet is None:
                raise ArenaV3Conflict("Locked winner reward is unavailable")
            transaction = _wallet_transaction(
                db,
                player_id=operation.player_id,
                amount=amount,
                balance_before=_money(wallet.efc_balance),
                balance_after=_money(wallet.efc_balance),
                kind="ARENA_V4_REWARD_LOCK_ROLLBACK",
                description=f"Arena V4 match #{match.id} reward lock reversed",
            )
        elif operation.operation_type == "STAKE_CONSUME":
            wallet = restore_locked_stake_efc(
                db, operation.player_id, amount
            )
            if wallet is None:
                raise ArenaV3Conflict("Arena V4 stake rollback failed")
            transaction = _wallet_transaction(
                db,
                player_id=operation.player_id,
                amount=amount,
                balance_before=_money(wallet.efc_balance),
                balance_after=_money(wallet.efc_balance),
                kind="ARENA_V4_STAKE_ROLLBACK",
                description=f"Arena V4 match #{match.id} stake restored",
            )
        elif operation.operation_type == "STAKE_REFUND":
            if (operation.operation_metadata or {}).get("locked"):
                wallet = remove_locked_reward_efc(
                    db, operation.player_id, amount
                )
                if wallet is not None:
                    wallet = restore_locked_stake_efc(
                        db, operation.player_id, amount
                    )
            else:
                wallet = reverse_refund_to_locked_efc(
                    db, operation.player_id, amount
                )
            if wallet is None:
                raise ArenaV3Conflict(
                    "Refund was spent and cannot be revised automatically"
                )
            transaction = _wallet_transaction(
                db,
                player_id=operation.player_id,
                amount=amount,
                balance_before=_money(wallet.efc_balance) + amount,
                balance_after=_money(wallet.efc_balance),
                kind="ARENA_V4_REFUND_ROLLBACK",
                description=f"Arena V4 match #{match.id} refund reversed",
            )
        operation.status = ArenaV4SettlementOperationStatus.REVERSED
        _operation(
            repository,
            match=match,
            result_version=new_version,
            player_id=operation.player_id,
            operation_type=f"ROLLBACK_{operation.operation_type}",
            amount=amount,
            wallet_transaction_id=transaction.id if transaction else None,
            metadata={"old_result_version": old_version},
            reverses_operation_id=operation.id,
        )


def _apply_revised_financial_result(
    db, repository, match, *, decision, result_version, now
):
    stake = _money(match.stake_efc)
    total_pool = _money(stake * Decimal("2"))
    match.total_pool_efc = total_pool
    if decision in {
        ArenaV4ResultType.PLAYER_A_WIN,
        ArenaV4ResultType.PLAYER_B_WIN,
    }:
        commission = _money(total_pool * FEE_PERCENT / Decimal("100"))
        reward = _money(total_pool - commission)
        winner_id = (
            match.owner_id
            if decision == ArenaV4ResultType.PLAYER_A_WIN
            else match.opponent_id
        )
        match.commission_efc = commission
        match.winner_reward_efc = reward
        match.winner_id = winner_id
        match.loser_id = (
            match.opponent_id if winner_id == match.owner_id else match.owner_id
        )
        match.reward_hold_status = ArenaV4RewardHoldStatus.APPEAL_HOLD
        match.reward_release_at = now
        _consume_stake(db, repository, match, match.owner_id, result_version)
        _consume_stake(db, repository, match, match.opponent_id, result_version)
        _lock_reward(
            db, repository, match, winner_id, reward, result_version
        )
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
        match.reward_hold_status = ArenaV4RewardHoldStatus.LOCKED
        match.reward_release_at = now
        _lock_refund(db, repository, match, match.owner_id, result_version)
        _lock_refund(db, repository, match, match.opponent_id, result_version)
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
    match.cancel_reason = (
        "APPEAL_ADMIN_CANCEL"
        if decision == ArenaV4ResultType.CANCEL
        else None
    )


def _release_appeal_reward(db, repository, match, *, now):
    if match.reward_hold_status not in {
        ArenaV4RewardHoldStatus.LOCKED,
        ArenaV4RewardHoldStatus.APPEAL_HOLD,
    }:
        return
    credits = [
        item for item in repository.list_settlement_operations_for_update(
            match.id, match.result_version
        )
        if item.operation_type in {"REWARD_LOCK", "STAKE_REFUND"}
        and item.status == ArenaV4SettlementOperationStatus.COMPLETED
    ]
    for credit in credits:
        amount = _money(credit.amount_efc)
        wallet = release_locked_reward_efc(db, credit.player_id, amount)
        if wallet is None:
            raise ArenaV3Conflict("Arena V4 locked reward is unavailable")
        balance_after = _money(wallet.efc_balance)
        transaction = _wallet_transaction(
            db,
            player_id=credit.player_id,
            amount=amount,
            balance_before=balance_after - amount,
            balance_after=balance_after,
            kind="ARENA_V4_REWARD_RELEASED",
            description=f"Arena V4 match #{match.id} appeal reward released",
        )
        _operation(
            repository,
            match=match,
            result_version=match.result_version,
            player_id=credit.player_id,
            operation_type="REWARD_RELEASE",
            amount=amount,
            wallet_transaction_id=transaction.id,
            metadata={
                "released_at": now.isoformat(),
                "source": "APPEAL_RESOLUTION",
            },
        )
        queue_v4_notification(
            repository,
            match_id=match.id,
            recipient_id=credit.player_id,
            event_type="REWARD_RELEASED",
            dedup_key=(
                f"arena-v4:{match.id}:{match.result_version}:"
                f"REWARD_RELEASED:{credit.player_id}"
            ),
        )
    match.reward_hold_status = ArenaV4RewardHoldStatus.AVAILABLE
    match.reward_release_at = now


def _apply_division_admin_result(
    db, *, repository, match, review, payload, now, decision
):
    from app.services.division import DivisionService, DivisionServiceError

    owner_score = getattr(payload, "owner_score", None)
    opponent_score = getattr(payload, "opponent_score", None)
    try:
        division_match = DivisionService(db).finish_arena_result(
            match.id,
            player_a_score=owner_score,
            player_b_score=opponent_score,
            cancelled=decision == ArenaV4ResultType.CANCEL,
            commit=False,
        )
    except DivisionServiceError as exc:
        raise ArenaV3Conflict(str(exc)) from exc

    result_version = match.result_version + 1
    match.owner_score = owner_score
    match.opponent_score = opponent_score
    match.current_result_type = decision
    match.result_version = result_version
    match.current_decision_id = review.id
    if match.initial_decision_id is None:
        match.initial_decision_id = review.id
    match.result_source = "ADMIN"
    match.appeal_deadline_at = now + timedelta(minutes=REWARD_HOLD_MINUTES)
    match.has_appeal = False
    match.stake_efc = Decimal("0.00")
    match.total_pool_efc = Decimal("0.00")
    match.commission_efc = Decimal("0.00")
    match.winner_reward_efc = Decimal("0.00")
    match.winner_id = division_match.winner_id
    match.loser_id = division_match.loser_id
    match.reward_hold_status = ArenaV4RewardHoldStatus.NONE
    match.reward_release_at = None
    match.settlement_status = ArenaV3SettlementStatus.COMPLETED
    match.cancel_reason = (
        "ADMIN_CANCEL" if decision == ArenaV4ResultType.CANCEL else None
    )

    repository.add_result_revision(ArenaV4ResultRevision(
        match_id=match.id,
        version=result_version,
        review_id=review.id,
        previous_result_type=None,
        new_result_type=decision.value,
        previous_winner_id=None,
        new_winner_id=match.winner_id,
        new_owner_score=owner_score,
        new_opponent_score=opponent_score,
        new_reward_efc=Decimal("0.00"),
        new_fee_efc=Decimal("0.00"),
        admin_id=review.assigned_admin_id,
        reason=payload.reason or "INITIAL_DIVISION_DECISION",
    ))
    _queue_initial_result_notifications(repository, match, decision)
    transition_arena_v3(match, ArenaV3Status.FINISHED)
    match.settled_at = now
    match.finished_at = now
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type="DIVISION_ADMIN_RESULT_COMPLETED",
        from_status=ArenaV3Status.WAITING_ADMIN.value,
        to_status=ArenaV3Status.FINISHED.value,
        actor_type="ADMIN",
        actor_id=review.assigned_admin_id,
        idempotency_key=f"division-admin-result:{review.id}",
        event_metadata={
            "decision": decision.value,
            "result_version": result_version,
            "points_awarded": 3 if match.winner_id is not None else 0,
        },
    ))


def apply_admin_settlement(
    db, *, repository, match, review, payload, now=None, decision=None
):
    if match.opponent_id is None:
        raise ArenaV3Conflict("Arena V4 opponent is missing")
    if match.settlement_status != ArenaV3SettlementStatus.NOT_STARTED:
        raise ArenaV3Conflict("Arena V4 match is already settled")

    now = now or datetime.now(timezone.utc)
    decision = decision or result_from_score(
        payload.owner_score, payload.opponent_score
    )
    if match.match_type == "DIVISION":
        _apply_division_admin_result(
            db,
            repository=repository,
            match=match,
            review=review,
            payload=payload,
            now=now,
            decision=decision,
        )
        return

    result_version = match.result_version + 1
    stake = _money(match.stake_efc)
    total_pool = _money(stake * Decimal("2"))
    match.total_pool_efc = total_pool
    owner_score = getattr(payload, "owner_score", None)
    opponent_score = getattr(payload, "opponent_score", None)
    match.owner_score = owner_score
    match.opponent_score = opponent_score
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
        match.reward_hold_status = ArenaV4RewardHoldStatus.LOCKED
        match.reward_release_at = now + timedelta(minutes=REWARD_HOLD_MINUTES)
        _lock_refund(db, repository, match, match.owner_id, result_version)
        _lock_refund(db, repository, match, match.opponent_id, result_version)
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
        new_owner_score=owner_score,
        new_opponent_score=opponent_score,
        new_reward_efc=match.winner_reward_efc,
        new_fee_efc=match.commission_efc,
        admin_id=review.assigned_admin_id,
        reason=payload.reason or "INITIAL_ADMIN_DECISION",
    ))
    _queue_initial_result_notifications(repository, match, decision)
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


def _resolve_division_appeal(
    db,
    *,
    repository,
    match,
    review,
    appeal,
    action,
    owner_score,
    opponent_score,
    reason,
    now,
):
    from app.services.division import DivisionService, DivisionServiceError

    old_version = match.result_version
    old_result = match.current_result_type
    old_winner_id = match.winner_id
    old_owner_score = match.owner_score
    old_opponent_score = match.opponent_score

    if action.value == "KEEP_RESULT":
        event_type = "DIVISION_APPEAL_RESULT_KEPT"
    else:
        cancelled = action.value == "CANCEL_MATCH"
        if not cancelled:
            if (
                owner_score == old_owner_score
                and opponent_score == old_opponent_score
            ):
                raise ArenaV3Conflict(
                    "Updated score must differ from current score"
                )
            new_result = result_from_score(owner_score, opponent_score)
        else:
            owner_score = None
            opponent_score = None
            new_result = ArenaV4ResultType.CANCEL
        try:
            division_match = DivisionService(db).revise_arena_result(
                match.id,
                player_a_score=owner_score,
                player_b_score=opponent_score,
                cancelled=cancelled,
                commit=False,
            )
        except DivisionServiceError as exc:
            raise ArenaV3Conflict(str(exc)) from exc

        new_version = old_version + 1
        match.owner_score = owner_score
        match.opponent_score = opponent_score
        match.current_result_type = new_result
        match.result_version = new_version
        match.current_decision_id = review.id
        match.result_source = "ADMIN_APPEAL"
        match.winner_id = division_match.winner_id
        match.loser_id = division_match.loser_id
        match.cancel_reason = (
            "APPEAL_ADMIN_CANCEL" if cancelled else None
        )
        match.stake_efc = Decimal("0.00")
        match.total_pool_efc = Decimal("0.00")
        match.commission_efc = Decimal("0.00")
        match.winner_reward_efc = Decimal("0.00")
        match.reward_hold_status = ArenaV4RewardHoldStatus.NONE
        match.reward_release_at = None
        match.settlement_status = ArenaV3SettlementStatus.COMPLETED
        repository.add_result_revision(ArenaV4ResultRevision(
            match_id=match.id,
            version=new_version,
            review_id=review.id,
            appeal_id=appeal.id,
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
            admin_id=review.assigned_admin_id,
            reason=reason,
        ))
        event_type = (
            "DIVISION_APPEAL_SCORE_UPDATED"
            if not cancelled
            else "DIVISION_APPEAL_MATCH_CANCELLED"
        )

    for player_id in (match.owner_id, match.opponent_id):
        queue_v4_notification(
            repository,
            match_id=match.id,
            recipient_id=player_id,
            event_type="APPEAL_RESOLVED",
            dedup_key=(
                f"division:{match.id}:appeal-resolved:"
                f"{review.id}:{player_id}"
            ),
        )
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type=event_type,
        from_status=ArenaV3Status.FINISHED.value,
        to_status=ArenaV3Status.FINISHED.value,
        actor_type="ADMIN",
        actor_id=review.assigned_admin_id,
        idempotency_key=f"division-appeal-resolution:{review.id}",
        event_metadata={
            "action": action.value,
            "old_result_version": old_version,
            "new_result_version": match.result_version,
        },
    ))


def resolve_appeal_settlement(
    db,
    *,
    repository,
    match,
    review,
    appeal,
    action,
    owner_score=None,
    opponent_score=None,
    reason: str,
    now=None,
):
    now = now or datetime.now(timezone.utc)
    old_version = match.result_version
    old_result = match.current_result_type
    old_winner_id = match.winner_id
    old_owner_score = match.owner_score
    old_opponent_score = match.opponent_score
    old_reward = _money(match.winner_reward_efc)
    old_fee = _money(match.commission_efc)

    if match.match_type == "DIVISION":
        _resolve_division_appeal(
            db,
            repository=repository,
            match=match,
            review=review,
            appeal=appeal,
            action=action,
            owner_score=owner_score,
            opponent_score=opponent_score,
            reason=reason,
            now=now,
        )
        return

    if action.value == "KEEP_RESULT":
        _release_appeal_reward(db, repository, match, now=now)
        event_type = "APPEAL_RESULT_KEPT"
    else:
        if action.value == "UPDATE_SCORE":
            if (
                owner_score == old_owner_score
                and opponent_score == old_opponent_score
            ):
                raise ArenaV3Conflict("Updated score must differ from current score")
            new_result = result_from_score(owner_score, opponent_score)
        else:
            owner_score = None
            opponent_score = None
            new_result = ArenaV4ResultType.CANCEL
        new_version = old_version + 1
        _rollback_wallet_settlement(
            db,
            repository,
            match,
            old_version=old_version,
            new_version=new_version,
        )
        match.owner_score = owner_score
        match.opponent_score = opponent_score
        match.current_result_type = new_result
        match.result_version = new_version
        match.current_decision_id = review.id
        match.result_source = "ADMIN_APPEAL"
        _apply_revised_financial_result(
            db,
            repository,
            match,
            decision=new_result,
            result_version=new_version,
            now=now,
        )
        repository.add_result_revision(ArenaV4ResultRevision(
            match_id=match.id,
            version=new_version,
            review_id=review.id,
            appeal_id=appeal.id,
            previous_result_type=old_result.value if old_result else None,
            new_result_type=new_result.value,
            previous_winner_id=old_winner_id,
            new_winner_id=match.winner_id,
            previous_owner_score=old_owner_score,
            previous_opponent_score=old_opponent_score,
            new_owner_score=owner_score,
            new_opponent_score=opponent_score,
            previous_reward_efc=old_reward,
            new_reward_efc=match.winner_reward_efc,
            previous_fee_efc=old_fee,
            new_fee_efc=match.commission_efc,
            admin_id=review.assigned_admin_id,
            reason=reason,
        ))
        _recalculate_player_stats(repository, match.owner_id)
        _recalculate_player_stats(repository, match.opponent_id)
        _release_appeal_reward(db, repository, match, now=now)
        event_type = (
            "APPEAL_SCORE_UPDATED"
            if action.value == "UPDATE_SCORE"
            else "APPEAL_MATCH_CANCELLED"
        )

    for player_id in (match.owner_id, match.opponent_id):
        dedup_key = (
            f"arena-v4:{match.id}:appeal-resolved:"
            f"{review.id}:{player_id}"
        )
        queue_v4_notification(
            repository,
            match_id=match.id,
            recipient_id=player_id,
            event_type="APPEAL_RESOLVED",
            dedup_key=dedup_key,
        )
    repository.add_event(ArenaV3MatchEvent(
        match_id=match.id,
        event_type=event_type,
        from_status=ArenaV3Status.FINISHED.value,
        to_status=ArenaV3Status.FINISHED.value,
        actor_type="ADMIN",
        actor_id=review.assigned_admin_id,
        idempotency_key=f"appeal-resolution:{review.id}",
        event_metadata={
            "action": action.value,
            "old_result_version": old_version,
            "new_result_version": match.result_version,
            "old_result": old_result.value if old_result else None,
            "new_result": (
                match.current_result_type.value
                if match.current_result_type else None
            ),
        },
    ))
