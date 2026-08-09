"""Authoritative, side-effect-free rules for the Wall Rush board game."""

from collections import deque
from dataclasses import dataclass, replace
from enum import Enum
from typing import FrozenSet, Union

BOARD_ROWS = 13
BOARD_COLUMNS = 9
STARTING_WALLS = 10

Position = tuple[int, int]


class Player(str, Enum):
    RED = "RED"
    BLUE = "BLUE"

    @property
    def opponent(self) -> "Player":
        return Player.BLUE if self is Player.RED else Player.RED


class Orientation(str, Enum):
    HORIZONTAL = "HORIZONTAL"
    VERTICAL = "VERTICAL"


@dataclass(frozen=True)
class Wall:
    row: int
    column: int
    orientation: Orientation


@dataclass(frozen=True)
class MoveAction:
    destination: Position


@dataclass(frozen=True)
class WallAction:
    wall: Wall


Action = Union[MoveAction, WallAction]


@dataclass(frozen=True)
class GameState:
    red: Position = (BOARD_ROWS - 1, 2)
    blue: Position = (BOARD_ROWS - 1, 6)
    current_player: Player = Player.RED
    walls: FrozenSet[Wall] = frozenset()
    red_walls_remaining: int = STARTING_WALLS
    blue_walls_remaining: int = STARTING_WALLS
    turn_number: int = 1
    winner: Player | None = None


class InvalidAction(ValueError):
    pass


def _inside(position: Position) -> bool:
    row, column = position
    return 0 <= row < BOARD_ROWS and 0 <= column < BOARD_COLUMNS


def _wall_edges(wall: Wall) -> frozenset[frozenset[Position]]:
    row, column = wall.row, wall.column
    if not (0 <= row < BOARD_ROWS - 1 and 0 <= column < BOARD_COLUMNS - 1):
        raise InvalidAction("Wall is outside the board")
    if wall.orientation is Orientation.HORIZONTAL:
        pairs = (
            ((row, column), (row + 1, column)),
            ((row, column + 1), (row + 1, column + 1)),
        )
    else:
        pairs = (
            ((row, column), (row, column + 1)),
            ((row + 1, column), (row + 1, column + 1)),
        )
    return frozenset(frozenset(pair) for pair in pairs)


def blocked_edges(walls: FrozenSet[Wall]) -> frozenset[frozenset[Position]]:
    edges: set[frozenset[Position]] = set()
    for wall in walls:
        edges.update(_wall_edges(wall))
    return frozenset(edges)


def _neighbours(position: Position, edges: frozenset[frozenset[Position]]):
    row, column = position
    for candidate in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
        if _inside(candidate) and frozenset((position, candidate)) not in edges:
            yield candidate


def has_finish_path(start: Position, walls: FrozenSet[Wall]) -> bool:
    edges = blocked_edges(walls)
    queue = deque([start])
    visited = {start}
    while queue:
        position = queue.popleft()
        if position[0] == 0:
            return True
        for candidate in _neighbours(position, edges):
            if candidate not in visited:
                visited.add(candidate)
                queue.append(candidate)
    return False


def _place_wall(state: GameState, action: WallAction) -> GameState:
    wall = action.wall
    remaining = state.red_walls_remaining if state.current_player is Player.RED else state.blue_walls_remaining
    if remaining <= 0:
        raise InvalidAction("No walls remaining")

    new_edges = _wall_edges(wall)
    existing_edges = blocked_edges(state.walls)
    if new_edges & existing_edges:
        raise InvalidAction("Wall overlaps an existing wall")
    if any(
        item.row == wall.row
        and item.column == wall.column
        and item.orientation is not wall.orientation
        for item in state.walls
    ):
        raise InvalidAction("Walls cannot cross")

    walls = state.walls | frozenset((wall,))
    if not has_finish_path(state.red, walls) or not has_finish_path(state.blue, walls):
        raise InvalidAction("A wall cannot completely block a player's finish path")

    if state.current_player is Player.RED:
        return replace(state, walls=walls, red_walls_remaining=remaining - 1)
    return replace(state, walls=walls, blue_walls_remaining=remaining - 1)


def _move(state: GameState, action: MoveAction) -> GameState:
    source = state.red if state.current_player is Player.RED else state.blue
    occupied = state.blue if state.current_player is Player.RED else state.red
    destination = action.destination
    if not _inside(destination):
        raise InvalidAction("Destination is outside the board")
    if destination == occupied:
        raise InvalidAction("Players cannot occupy the same cell")
    if destination not in _neighbours(source, blocked_edges(state.walls)):
        raise InvalidAction("Ball must move one unblocked orthogonal cell")
    if state.current_player is Player.RED:
        return replace(state, red=destination)
    return replace(state, blue=destination)


def apply_action(state: GameState, action: Action) -> GameState:
    """Apply exactly one move or wall action and hand the turn to the opponent."""
    if state.winner is not None:
        raise InvalidAction("Match is already finished")
    if isinstance(action, MoveAction):
        updated = _move(state, action)
    elif isinstance(action, WallAction):
        updated = _place_wall(state, action)
    else:
        raise InvalidAction("A turn must contain exactly one supported action")

    position = updated.red if state.current_player is Player.RED else updated.blue
    winner = state.current_player if position[0] == 0 else None
    return replace(
        updated,
        current_player=state.current_player.opponent,
        turn_number=state.turn_number + 1,
        winner=winner,
    )
