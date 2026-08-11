from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.models.division import DivisionMatch, DivisionTicketLedger


DIVISION_TABLES = (
    DivisionMatch.__table__,
    DivisionTicketLedger.__table__,
)


def run_division_migrations(bind: Engine | Connection) -> None:
    """Create additive Division matchmaking storage and safe Arena constraints."""
    for table in DIVISION_TABLES:
        table.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    wallet_columns = (
        {
            column["name"]
            for column in inspector.get_columns("game_ticket_wallets")
        }
        if inspector.has_table("game_ticket_wallets")
        else set()
    )
    arena_checks = (
        {
            constraint["name"]
            for constraint in inspector.get_check_constraints("arena_matches")
        }
        if inspector.has_table("arena_matches")
        else set()
    )

    connection = bind.connect() if isinstance(bind, Engine) else bind
    owns_connection = isinstance(bind, Engine)
    try:
        with connection.begin():
            if (
                wallet_columns
                and "locked_tournament_tickets" not in wallet_columns
            ):
                connection.execute(
                    text(
                        "ALTER TABLE game_ticket_wallets "
                        "ADD COLUMN locked_tournament_tickets "
                        "INTEGER NOT NULL DEFAULT 0"
                    )
                )
                if connection.dialect.name == "postgresql":
                    connection.execute(
                        text(
                            "ALTER TABLE game_ticket_wallets "
                            "ADD CONSTRAINT "
                            "ck_game_ticket_wallet_locked_tournament "
                            "CHECK (locked_tournament_tickets >= 0)"
                        )
                    )

            if (
                connection.dialect.name == "postgresql"
                and "ck_arena_matches_stake_by_type" not in arena_checks
            ):
                connection.execute(
                    text(
                        "ALTER TABLE arena_matches DROP CONSTRAINT IF EXISTS "
                        "ck_arena_matches_positive_stake"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE arena_matches ADD CONSTRAINT "
                        "ck_arena_matches_stake_by_type CHECK ("
                        "(match_type = 'DIVISION' AND stake_efc = 0) OR "
                        "(match_type <> 'DIVISION' AND stake_efc > 0)"
                        ")"
                    )
                )
    finally:
        if owns_connection:
            connection.close()
