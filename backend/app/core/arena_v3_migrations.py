from sqlalchemy.engine import Connection, Engine

from app.models.arena_v3 import (
    ArenaV3AIReview, ArenaV3Appeal, ArenaV3Match, ArenaV3MatchEvent,
    ArenaV3MatchScreenshot, ArenaV3NotificationDelivery, ArenaV3Stats,
)


ARENA_V3_TABLES = (
    ArenaV3Match.__table__,
    ArenaV3MatchScreenshot.__table__,
    ArenaV3AIReview.__table__,
    ArenaV3Appeal.__table__,
    ArenaV3MatchEvent.__table__,
    ArenaV3NotificationDelivery.__table__,
    ArenaV3Stats.__table__,
)


def run_arena_v3_migrations(bind: Engine | Connection) -> None:
    """Create only additive Arena V3 tables and their constraints/indexes."""
    for table in ARENA_V3_TABLES:
        table.create(bind=bind, checkfirst=True)
