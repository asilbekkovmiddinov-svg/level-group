from sqlalchemy import inspect, text
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
    inspector = inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("arena_ai_reviews")}
    appeal_columns = {
        column["name"]: column for column in inspector.get_columns("arena_appeals")
    }
    additions = {
        "winner_player_id": "BIGINT REFERENCES users (telegram_id)",
        "score": "VARCHAR(16)",
        "reason": "VARCHAR(255)",
    }
    connection = bind.connect() if isinstance(bind, Engine) else bind
    owns_connection = isinstance(bind, Engine)
    try:
        with connection.begin():
            for name, ddl in additions.items():
                if name not in existing:
                    connection.execute(text(
                        f"ALTER TABLE arena_ai_reviews ADD COLUMN {name} {ddl}"
                    ))
            stats_existing = {
                column["name"] for column in inspector.get_columns("arena_stats_v3")
            }
            stats_additions = {
                "draws": "INTEGER NOT NULL DEFAULT 0",
                "goals_for": "INTEGER NOT NULL DEFAULT 0",
                "goals_against": "INTEGER NOT NULL DEFAULT 0",
                "win_rate": "NUMERIC(5, 2) NOT NULL DEFAULT 0",
            }
            for name, ddl in stats_additions.items():
                if name not in stats_existing:
                    connection.execute(text(
                        f"ALTER TABLE arena_stats_v3 ADD COLUMN {name} {ddl}"
                    ))
            if connection.dialect.name == "postgresql":
                for name in ("submitted_by", "video_storage_key", "file_hash"):
                    if not appeal_columns[name]["nullable"]:
                        connection.execute(text(
                            f"ALTER TABLE arena_appeals "
                            f"ALTER COLUMN {name} DROP NOT NULL"
                        ))
    finally:
        if owns_connection:
            connection.close()
