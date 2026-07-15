from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.crud import wheel


FRONTEND_CONTRACT = {
    ("NONE", Decimal("0")),
    ("EFC", Decimal("50")),
    ("EFC", Decimal("100")),
    ("UZS", Decimal("500")),
    ("EFC", Decimal("250")),
    ("EFC", Decimal("500")),
    ("UZS", Decimal("1000")),
    ("UZS", Decimal("5000")),
    ("COIN_ORDER", Decimal("130")),
    ("COIN_ORDER", Decimal("2000")),
}


def reward_pair(reward):
    return reward["type"], Decimal(str(reward["amount"]))


def settings(global_spin_count=0, next_130_coin_spin=10**9):
    return SimpleNamespace(
        global_spin_count=global_spin_count,
        next_130_coin_spin=next_130_coin_spin,
        next_jackpot_spin=wheel.JACKPOT_INTERVAL,
        jackpot_coin_amount=2000,
        coin_130_amount=130,
    )


def test_base_rewards_match_only_frontend_random_sectors():
    assert [reward_pair(reward) for reward in wheel.BASE_REWARDS] == [
        ("NONE", Decimal("0")),
        ("EFC", Decimal("50")),
        ("EFC", Decimal("100")),
        ("UZS", Decimal("500")),
    ]
    assert {reward["code"] for reward in wheel.BASE_REWARDS} == {
        "lose", "efc_50", "efc_100", "uzs_500",
    }


@pytest.mark.parametrize(
    ("minimum", "expected"),
    [
        (wheel.EFC_250_INTERVAL_MIN, ("EFC", Decimal("250"))),
        (wheel.EFC_500_INTERVAL_MIN, ("EFC", Decimal("500"))),
        (wheel.UZS_1000_INTERVAL_MIN, ("UZS", Decimal("1000"))),
        (wheel.UZS_5000_INTERVAL_MIN, ("UZS", Decimal("5000"))),
    ],
)
def test_interval_rewards_stay_in_frontend_contract(monkeypatch, minimum, expected):
    monkeypatch.setattr(
        wheel,
        "should_give_interval_reward",
        lambda _spin, candidate_min, _max: candidate_min == minimum,
    )
    reward = wheel.choose_reward(settings(global_spin_count=1))
    assert reward_pair(reward) == expected
    assert reward_pair(reward) in FRONTEND_CONTRACT


def test_coin_rewards_keep_authoritative_global_schedule(monkeypatch):
    monkeypatch.setattr(wheel.random, "randint", lambda minimum, maximum: minimum)

    coin_130_settings = settings(global_spin_count=64999, next_130_coin_spin=65000)
    coin_130 = wheel.choose_reward(coin_130_settings)
    assert reward_pair(coin_130) == ("COIN_ORDER", Decimal("130"))
    assert coin_130_settings.next_130_coin_spin == 130000

    jackpot_settings = settings(global_spin_count=99999)
    jackpot = wheel.choose_reward(jackpot_settings)
    assert reward_pair(jackpot) == ("COIN_ORDER", Decimal("2000"))
    assert jackpot_settings.next_jackpot_spin == 200000


def test_every_possible_reward_has_exact_frontend_type_and_amount(monkeypatch):
    possible = {reward_pair(reward) for reward in wheel.BASE_REWARDS}
    possible.update(
        {
            ("EFC", Decimal("250")),
            ("EFC", Decimal("500")),
            ("UZS", Decimal("1000")),
            ("UZS", Decimal("5000")),
            ("COIN_ORDER", Decimal("130")),
            ("COIN_ORDER", Decimal("2000")),
        }
    )
    assert possible == FRONTEND_CONTRACT
    assert "BONUS_SPIN" not in {reward_type for reward_type, _ in possible}
    assert ("EFC", Decimal("5")) not in possible
    assert ("EFC", Decimal("10")) not in possible
    assert ("EFC", Decimal("25")) not in possible


def test_uzs_reward_credits_wallet_and_creates_transaction(monkeypatch):
    wallet_after = SimpleNamespace(uzs_balance=Decimal("1500"))
    add_uzs = Mock(return_value=wallet_after)
    create_transaction = Mock()
    monkeypatch.setattr(wheel, "add_uzs_balance", add_uzs)
    monkeypatch.setattr(wheel, "create_transaction", create_transaction)

    reward = wheel.make_reward("uzs_500", wheel.REWARD_TYPE_UZS, 500, "500 UZS")
    wheel.apply_reward(
        db=Mock(),
        telegram_id=123,
        reward=reward,
        spin=Mock(),
        limit=Mock(),
    )

    assert add_uzs.call_args.kwargs["amount"] == Decimal("500.0000")
    transaction = create_transaction.call_args.kwargs
    assert transaction["currency"] == "UZS"
    assert transaction["amount"] == Decimal("500.0000")
    assert transaction["balance_before"] == Decimal("1000.0000")
    assert transaction["balance_after"] == Decimal("1500")
    assert transaction["type"] == "WHEEL_REWARD"
