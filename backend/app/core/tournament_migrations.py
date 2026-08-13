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
    """Create additive tournament storage without touching existing Arena data."""
    for table in TOURNAMENT_TABLES:
        table.create(bind=bind, checkfirst=True)
