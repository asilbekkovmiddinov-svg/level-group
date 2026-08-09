import pytest

from app.domain.wall_rush import (
    BOARD_ROWS, GameState, InvalidAction, MoveAction, Orientation, Player,
    Wall, WallAction, apply_action, has_finish_path,
)


def test_turn_accepts_exactly_one_action_and_changes_player():
    state = apply_action(GameState(), MoveAction((BOARD_ROWS - 2, 2)))
    assert state.red == (BOARD_ROWS - 2, 2)
    assert state.current_player is Player.BLUE
    assert state.turn_number == 2
    with pytest.raises(InvalidAction, match="exactly one"):
        apply_action(state, object())


def test_ball_moves_only_one_unblocked_orthogonal_cell():
    with pytest.raises(InvalidAction):
        apply_action(GameState(), MoveAction((BOARD_ROWS - 2, 3)))
    blocked = GameState(walls=frozenset({Wall(BOARD_ROWS - 2, 2, Orientation.HORIZONTAL)}))
    with pytest.raises(InvalidAction, match="unblocked"):
        apply_action(blocked, MoveAction((BOARD_ROWS - 2, 2)))


def test_wall_costs_one_and_overlap_or_crossing_is_rejected():
    wall = Wall(4, 3, Orientation.HORIZONTAL)
    state = apply_action(GameState(), WallAction(wall))
    assert state.red_walls_remaining == 9
    with pytest.raises(InvalidAction, match="overlaps"):
        apply_action(state, WallAction(Wall(4, 2, Orientation.HORIZONTAL)))
    with pytest.raises(InvalidAction, match="cross"):
        apply_action(state, WallAction(Wall(4, 3, Orientation.VERTICAL)))


def test_wall_cannot_remove_every_finish_path():
    walls = frozenset({
        Wall(BOARD_ROWS - 2, 1, Orientation.VERTICAL),
        Wall(BOARD_ROWS - 2, 2, Orientation.VERTICAL),
    })
    state = GameState(walls=walls, red_walls_remaining=2)
    assert has_finish_path(state.red, state.walls)
    with pytest.raises(InvalidAction, match="finish path"):
        apply_action(
            state,
            WallAction(Wall(BOARD_ROWS - 2, 1, Orientation.HORIZONTAL)),
        )


def test_reaching_top_row_finishes_match():
    state = GameState(red=(1, 2))
    finished = apply_action(state, MoveAction((0, 2)))
    assert finished.winner is Player.RED
    with pytest.raises(InvalidAction, match="finished"):
        apply_action(finished, MoveAction((BOARD_ROWS - 2, 6)))
