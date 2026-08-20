import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.penalty_duel import (
    PenaltyDuelMatch,
    PenaltyDuelMode,
    PenaltyDuelRound,
    PenaltyDuelStatus,
    PenaltyDuelSubmission,
)
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.services.penalty_duel import join_match, match_response
from app.services.penalty_duel_single_choice import player_role, submit_single_choice


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__,
        PenaltyDuelMatch.__table__,
        PenaltyDuelSubmission.__table__,
        PenaltyDuelRound.__table__,
        GameTicketWallet.__table__,
        GameTicketLedger.__table__,
    ])
    session = sessionmaker(bind=engine)()
    session.add_all([
        User(telegram_id=101, first_name="Asil"),
        User(telegram_id=202, first_name="Jocker"),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _start(db):
    waiting = join_match(db, 101, PenaltyDuelMode.FREE)
    active = join_match(db, 202, PenaltyDuelMode.FREE)
    assert waiting.id == active.id
    return active


def _submit_shot(db, match, goal: bool):
    shot = match.round_number
    if shot % 2 == 1:
        player_one_direction = "top-left" if goal else "center"
        player_two_direction = "center"
    else:
        player_one_direction = "center"
        player_two_direction = "top-left" if goal else "center"
    match = submit_single_choice(
        db, match.id, 101, player_one_direction, f"p1-shot-{shot:02d}",
    )
    return submit_single_choice(
        db, match.id, 202, player_two_direction, f"p2-shot-{shot:02d}",
    )


def test_roles_and_score_alternate_by_shot(db):
    match = _start(db)
    assert player_role(match, 101) == "KICK"
    assert player_role(match, 202) == "KEEPER"
    match = _submit_shot(db, match, goal=True)
    assert (match.player_one_score, match.player_two_score) == (1, 0)
    assert player_role(match, 101) == "KEEPER"
    assert player_role(match, 202) == "KICK"
    match = _submit_shot(db, match, goal=True)
    assert (match.player_one_score, match.player_two_score) == (1, 1)
    assert len(match_response(db, match, 101)["history"]) == 2


def test_regulation_finishes_early_when_comeback_is_impossible(db):
    match = _start(db)
    for goal in (True, False, True, False, True):
        match = _submit_shot(db, match, goal)
        assert match.status == PenaltyDuelStatus.ACTIVE
    match = _submit_shot(db, match, goal=False)
    assert match.status == PenaltyDuelStatus.FINISHED
    assert match.winner_id == 101
    assert (match.player_one_score, match.player_two_score) == (3, 0)
    assert match.round_number == 6


def test_tied_regulation_uses_complete_sudden_death_pairs(db):
    match = _start(db)
    for _ in range(10):
        match = _submit_shot(db, match, goal=True)
    assert match.status == PenaltyDuelStatus.ACTIVE
    assert match.round_number == 11
    assert (match.player_one_score, match.player_two_score) == (5, 5)

    match = _submit_shot(db, match, goal=True)
    assert match.status == PenaltyDuelStatus.ACTIVE
    assert match.round_number == 12
    match = _submit_shot(db, match, goal=False)
    assert match.status == PenaltyDuelStatus.FINISHED
    assert match.winner_id == 101
    assert (match.player_one_score, match.player_two_score) == (6, 5)
