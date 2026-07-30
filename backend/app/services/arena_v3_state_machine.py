from app.models.arena_v3 import ArenaV3Status


class ArenaV3InvalidTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[ArenaV3Status, frozenset[ArenaV3Status]] = {
    ArenaV3Status.OPEN: frozenset({ArenaV3Status.READY, ArenaV3Status.CANCELLED}),
    ArenaV3Status.READY: frozenset({ArenaV3Status.WAITING_ROOM_CODE, ArenaV3Status.CANCELLED}),
    ArenaV3Status.WAITING_ROOM_CODE: frozenset({ArenaV3Status.PLAYING, ArenaV3Status.CANCELLED}),
    ArenaV3Status.PLAYING: frozenset({ArenaV3Status.WAITING_SCREENSHOT}),
    ArenaV3Status.WAITING_SCREENSHOT: frozenset({
        ArenaV3Status.AI_REVIEW,
        ArenaV3Status.CANCELLED,
    }),
    ArenaV3Status.AI_REVIEW: frozenset({ArenaV3Status.FINISHED, ArenaV3Status.CANCELLED}),
    ArenaV3Status.FINISHED: frozenset(),
    ArenaV3Status.CANCELLED: frozenset(),
}


def ensure_arena_v3_transition(current: ArenaV3Status, target: ArenaV3Status) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ArenaV3InvalidTransition(
            f"Arena V3 transition {current.value} -> {target.value} is not allowed"
        )


def transition_arena_v3(match, target: ArenaV3Status):
    ensure_arena_v3_transition(ArenaV3Status(match.status), target)
    match.status = target
    match.version += 1
    return match
