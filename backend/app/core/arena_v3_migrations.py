from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.models.arena_v3 import (
    ArenaV3AIReview, ArenaV3Appeal, ArenaV3Match, ArenaV3MatchEvent,
    ArenaV3MatchScreenshot, ArenaV3NotificationDelivery, ArenaV3Stats,
    ArenaV4AdminReview, ArenaV4ResultRevision, ArenaV4SettlementOperation,
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

ARENA_V4_TABLES = (
    ArenaV4AdminReview.__table__,
    ArenaV4ResultRevision.__table__,
    ArenaV4SettlementOperation.__table__,
)


def _columns(inspector, table_name):
    return {
        column["name"]: column for column in inspector.get_columns(table_name)
    }


def run_arena_v3_migrations(bind: Engine | Connection) -> None:
    """Create additive Arena V3/V4 tables, columns, constraints and indexes."""
    for table in ARENA_V3_TABLES:
        table.create(bind=bind, checkfirst=True)
    for table in ARENA_V4_TABLES:
        table.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    ai_columns = _columns(inspector, "arena_ai_reviews")
    appeal_columns = _columns(inspector, "arena_appeals")
    screenshot_columns = _columns(inspector, "arena_match_screenshots")
    match_columns = _columns(inspector, "arena_matches")
    wallet_columns = (
        _columns(inspector, "wallets") if inspector.has_table("wallets") else None
    )
    stats_columns = _columns(inspector, "arena_stats_v3")
    connection = bind.connect() if isinstance(bind, Engine) else bind
    owns_connection = isinstance(bind, Engine)
    try:
        with connection.begin():
            ai_additions = {
                "winner_player_id": "BIGINT REFERENCES users (telegram_id)",
                "score": "VARCHAR(16)",
                "reason": "VARCHAR(255)",
            }
            for name, ddl in ai_additions.items():
                if name not in ai_columns:
                    connection.execute(text(
                        f"ALTER TABLE arena_ai_reviews ADD COLUMN {name} {ddl}"
                    ))

            stats_additions = {
                "draws": "INTEGER NOT NULL DEFAULT 0",
                "goals_for": "INTEGER NOT NULL DEFAULT 0",
                "goals_against": "INTEGER NOT NULL DEFAULT 0",
                "win_rate": "NUMERIC(5, 2) NOT NULL DEFAULT 0",
            }
            for name, ddl in stats_additions.items():
                if name not in stats_columns:
                    connection.execute(text(
                        f"ALTER TABLE arena_stats_v3 ADD COLUMN {name} {ddl}"
                    ))

            match_additions = {
                "ticket_cost": "INTEGER NOT NULL DEFAULT 0",
                "owner_ticket_state": "VARCHAR(16)",
                "opponent_ticket_state": "VARCHAR(16)",
                "reward_hold_status": "VARCHAR(32) NOT NULL DEFAULT 'NONE'",
                "reward_release_at": "TIMESTAMP",
                "appeal_deadline_at": "TIMESTAMP",
                "has_appeal": "BOOLEAN NOT NULL DEFAULT false",
                "owner_result_confirmed_at": "TIMESTAMP",
                "opponent_result_confirmed_at": "TIMESTAMP",
                "admin_channel_message_id": "BIGINT",
                "current_result_type": "VARCHAR(32)",
                "result_version": "INTEGER NOT NULL DEFAULT 0",
                "current_decision_id": (
                    "INTEGER REFERENCES arena_admin_reviews (id)"
                ),
                "initial_decision_id": (
                    "INTEGER REFERENCES arena_admin_reviews (id)"
                ),
            }
            for name, ddl in match_additions.items():
                if name not in match_columns:
                    connection.execute(text(
                        f"ALTER TABLE arena_matches ADD COLUMN {name} {ddl}"
                    ))

            appeal_additions = {
                "reason": "VARCHAR(500)",
                "submitted_at": "TIMESTAMP",
                "deadline_at": "TIMESTAMP",
                "telegram_message_id": "BIGINT",
            }
            for name, ddl in appeal_additions.items():
                if name not in appeal_columns:
                    connection.execute(text(
                        f"ALTER TABLE arena_appeals ADD COLUMN {name} {ddl}"
                    ))

            if "telegram_message_id" not in screenshot_columns:
                connection.execute(text(
                    "ALTER TABLE arena_match_screenshots "
                    "ADD COLUMN telegram_message_id BIGINT"
                ))

            if (
                wallet_columns is not None
                and "locked_reward_efc" not in wallet_columns
            ):
                connection.execute(text(
                    "ALTER TABLE wallets ADD COLUMN locked_reward_efc "
                    "NUMERIC(18, 2) NOT NULL DEFAULT 0"
                ))

            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS "
                "ix_arena_matches_reward_release "
                "ON arena_matches (reward_hold_status, reward_release_at)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_arena_matches_has_appeal "
                "ON arena_matches (has_appeal)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_arena_appeal_deadline "
                "ON arena_appeals (deadline_at)"
            ))
            connection.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_arena_appeal_match "
                "ON arena_appeals (match_id)"
            ))

            if connection.dialect.name == "postgresql":
                connection.execute(text(
                    "ALTER TABLE arena_matches DROP CONSTRAINT IF EXISTS "
                    "ck_arena_matches_stake_by_mode"
                ))
                connection.execute(text(
                    "ALTER TABLE arena_matches ADD CONSTRAINT "
                    "ck_arena_matches_stake_by_mode CHECK ("
                    "(match_type IN ('DIVISION', 'TOURNAMENT') AND stake_efc = 0) OR "
                    "(match_type = 'STANDARD' AND stake_efc >= 0) OR "
                    "(match_type NOT IN ('DIVISION', 'TOURNAMENT', 'STANDARD') "
                    "AND stake_efc > 0))"
                ))
                connection.execute(text(
                    "ALTER TABLE arena_matches DROP CONSTRAINT IF EXISTS "
                    "ck_arena_matches_ticket_cost"
                ))
                connection.execute(text(
                    "ALTER TABLE arena_matches ADD CONSTRAINT "
                    "ck_arena_matches_ticket_cost CHECK (ticket_cost >= 0)"
                ))
                for name in ("submitted_by", "video_storage_key", "file_hash"):
                    column = appeal_columns.get(name)
                    if column is not None and not column["nullable"]:
                        connection.execute(text(
                            f"ALTER TABLE arena_appeals "
                            f"ALTER COLUMN {name} DROP NOT NULL"
                        ))
    finally:
        if owns_connection:
            connection.close()
