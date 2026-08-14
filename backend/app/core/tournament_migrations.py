from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.models.tournament import (
    Tournament,
    TournamentMatch,
    TournamentParticipant,
)


TOURNAMENT_TABLES = (
    Tournament.__table__,
    TournamentParticipant.__table__,
    TournamentMatch.__table__,
)


def run_tournament_migrations(bind: Engine | Connection) -> None:
    """Create tournament storage and enforce the current per-match ticket cost."""
    for table in TOURNAMENT_TABLES:
        table.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    ticket_constraint = next(
        (
            constraint
            for constraint in inspector.get_check_constraints("tournaments")
            if constraint["name"] == "ck_tournament_ticket_cost"
        ),
        None,
    )
    constraint_sql = (ticket_constraint or {}).get("sqltext", "")
    requires_postgres_constraint_upgrade = (
        bind.dialect.name == "postgresql"
        and "= 10" not in constraint_sql
        and "=10" not in constraint_sql
    )

    connection = bind.connect() if isinstance(bind, Engine) else bind
    owns_connection = isinstance(bind, Engine)
    try:
        with connection.begin():
            connection.execute(
                text("UPDATE tournaments SET ticket_cost = 10 WHERE ticket_cost <> 10")
            )
            if requires_postgres_constraint_upgrade:
                connection.execute(
                    text(
                        "ALTER TABLE tournaments DROP CONSTRAINT IF EXISTS "
                        "ck_tournament_ticket_cost"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE tournaments ADD CONSTRAINT "
                        "ck_tournament_ticket_cost CHECK (ticket_cost = 10)"
                    )
                )
    finally:
        if owns_connection:
            connection.close()
