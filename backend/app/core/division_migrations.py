from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.models.division import DivisionMatch, DivisionTicketLedger


DIVISION_TABLES = (
    DivisionMatch.__table__,
    DivisionTicketLedger.__table__,
)


def run_division_migrations(bind: Engine | Connection) -> None:
    """Create additive Division matchmaking storage and wallet lock column."""
    for table in DIVISION_TABLES:
        table.create(bind=bind, checkfirst=True)

    inspector = inspect(bind)
    if not inspector.has_table("game_ticket_wallets"):
        return

    wallet_columns = {
        column["name"]
        for column in inspector.get_columns("game_ticket_wallets")
    }
    if "locked_tournament_tickets" in wallet_columns:
        return

    connection = bind.connect() if isinstance(bind, Engine) else bind
    owns_connection = isinstance(bind, Engine)
    try:
        with connection.begin():
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
                        "ADD CONSTRAINT ck_game_ticket_wallet_locked_tournament "
                        "CHECK (locked_tournament_tickets >= 0)"
                    )
                )
    finally:
        if owns_connection:
            connection.close()
