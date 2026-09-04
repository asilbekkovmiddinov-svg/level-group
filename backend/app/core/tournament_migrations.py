from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.models.tournament import (
    MAX_TOURNAMENT_PARTICIPANTS,
    Tournament,
    TournamentDailyDelivery,
    TournamentMatch,
    TournamentParticipant,
)


TOURNAMENT_TABLES = (
    Tournament.__table__,
    TournamentParticipant.__table__,
    TournamentMatch.__table__,
    TournamentDailyDelivery.__table__,
)


def run_tournament_migrations(bind: Engine | Connection) -> None:
    """Create tournament storage and upgrade the simple group tournament fields."""
    for table in TOURNAMENT_TABLES:
        table.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    tournament_columns = {
        column["name"] for column in inspector.get_columns("tournaments")
    }
    participant_columns = {
        column["name"]
        for column in inspector.get_columns("tournament_participants")
    }
    constraints = inspector.get_check_constraints("tournaments")
    ticket_constraint = next(
        (
            constraint
            for constraint in constraints
            if constraint["name"] == "ck_tournament_ticket_cost"
        ),
        None,
    )
    constraint_sql = (ticket_constraint or {}).get("sqltext", "")
    requires_ticket_upgrade = (
        bind.dialect.name == "postgresql"
        and "1000000" not in constraint_sql
    )
    capacity_constraint = next(
        (
            constraint
            for constraint in constraints
            if constraint["name"] == "ck_tournament_capacity"
        ),
        None,
    )
    capacity_sql = (capacity_constraint or {}).get("sqltext", "")
    requires_capacity_upgrade = (
        bind.dialect.name == "postgresql"
        and str(MAX_TOURNAMENT_PARTICIPANTS) not in capacity_sql
    )

    connection = bind.connect() if isinstance(bind, Engine) else bind
    owns_connection = isinstance(bind, Engine)
    try:
        with connection.begin():
            tournament_additions = {
                "group_size": "INTEGER",
                "group_mode": "VARCHAR(16)",
                "entry_mode": "VARCHAR(32) NOT NULL DEFAULT 'TICKET'",
                "minimum_coin_purchase": "INTEGER NOT NULL DEFAULT 300",
                "duration_days": "INTEGER NOT NULL DEFAULT 7",
                "auto_start_when_full": "BOOLEAN NOT NULL DEFAULT FALSE",
                "announcement_channel_id": "VARCHAR(128)",
            }
            participant_additions = {
                "entry_ticket_state": "VARCHAR(16)",
                "goals_for": "INTEGER NOT NULL DEFAULT 0",
                "goals_against": "INTEGER NOT NULL DEFAULT 0",
                "qualification_order_id": "INTEGER",
                "qualification_coin_amount": "INTEGER",
            }
            for name, definition in tournament_additions.items():
                if name not in tournament_columns:
                    connection.execute(text(
                        f"ALTER TABLE tournaments ADD COLUMN {name} {definition}"
                    ))
            for name, definition in participant_additions.items():
                if name not in participant_columns:
                    connection.execute(text(
                        "ALTER TABLE tournament_participants ADD COLUMN "
                        f"{name} {definition}"
                    ))
            connection.execute(text(
                "UPDATE tournaments SET group_size = CASE "
                "WHEN group_count > 0 AND max_participants / group_count = 8 THEN 8 "
                "ELSE 4 END, group_mode = COALESCE(group_mode, 'POINTS') "
                "WHERE format = 'GROUP_PLAYOFF' AND group_size IS NULL"
            ))
            if bind.dialect.name == "postgresql":
                connection.execute(text(
                    "UPDATE tournaments SET duration_days = CASE "
                    "WHEN starts_at IS NOT NULL AND ends_at IS NOT NULL "
                    "THEN GREATEST(1, LEAST(365, "
                    "CAST(EXTRACT(EPOCH FROM (ends_at - starts_at)) / 86400 AS INTEGER))) "
                    "ELSE 7 END WHERE duration_days IS NULL"
                ))
            if requires_ticket_upgrade:
                connection.execute(
                    text(
                        "ALTER TABLE tournaments DROP CONSTRAINT IF EXISTS "
                        "ck_tournament_ticket_cost"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE tournaments ADD CONSTRAINT "
                        "ck_tournament_ticket_cost CHECK "
                        "(ticket_cost BETWEEN 0 AND 1000000)"
                    )
                )
            if requires_capacity_upgrade:
                connection.execute(
                    text(
                        "ALTER TABLE tournaments DROP CONSTRAINT IF EXISTS "
                        "ck_tournament_capacity"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE tournaments ADD CONSTRAINT "
                        "ck_tournament_capacity CHECK "
                        f"(max_participants BETWEEN 2 AND {MAX_TOURNAMENT_PARTICIPANTS})"
                    )
                )
            if bind.dialect.name == "postgresql":
                connection.execute(text(
                    "ALTER TABLE tournaments ALTER COLUMN starts_at DROP NOT NULL"
                ))
                connection.execute(text(
                    "ALTER TABLE tournaments ALTER COLUMN ends_at DROP NOT NULL"
                ))
                connection.execute(text(
                    "ALTER TABLE tournaments DROP CONSTRAINT IF EXISTS "
                    "ck_tournament_format_settings"
                ))
                connection.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_tournament_entry_mode "
                    "ON tournaments (entry_mode)"
                ))
                connection.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_tournament_participant_qualification_order "
                    "ON tournament_participants (qualification_order_id)"
                ))
                connection.execute(text(
                    "ALTER TABLE tournaments ADD CONSTRAINT "
                    "ck_tournament_format_settings CHECK ("
                    "(format = 'SINGLE_ELIMINATION' AND group_count IS NULL "
                    "AND qualifiers_per_group IS NULL AND group_size IS NULL "
                    "AND group_mode IS NULL) OR "
                    "(format = 'GROUP_PLAYOFF' AND group_count >= 1 "
                    "AND qualifiers_per_group >= 1 AND group_size IN (4, 8) "
                    "AND group_mode IN ('POINTS', 'ELIMINATION')))"
                ))
    finally:
        if owns_connection:
            connection.close()
