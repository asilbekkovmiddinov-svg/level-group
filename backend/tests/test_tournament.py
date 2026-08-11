from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.tournament import (
    Tournament,
    TournamentFormat,
    TournamentMatch,
    TournamentParticipant,
    TournamentParticipantStatus,
    TournamentStatus,
)
from app.models.user import User
from app.schemas.tournament import (
    TournamentApplicationDecision,
    TournamentCreate,
    TournamentMatchSchedule,
)
from app.services.tournament import TournamentService, TournamentServiceError


def build():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Tournament.__table__,
            TournamentParticipant.__table__,
            TournamentMatch.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add_all(
        [
            User(telegram_id=9001, username="admin"),
            User(telegram_id=101, username="alpha"),
            User(telegram_id=102, username="beta"),
        ]
    )
    db.commit()
    return db, engine


def payload(format=TournamentFormat.SINGLE_ELIMINATION):
    now = datetime.now(timezone.utc)
    group = format == TournamentFormat.GROUP_PLAYOFF
    return TournamentCreate(
        name="Summer Cup",
        format=format,
        max_participants=16,
        ticket_cost=1,
        group_count=4 if group else None,
        qualifiers_per_group=2 if group else None,
        registration_opens_at=now - timedelta(hours=1),
        registration_closes_at=now + timedelta(hours=1),
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(days=7),
    )


def test_admin_can_create_both_tournament_formats():
    db, engine = build()
    try:
        olympic = TournamentService(db).create(
            payload(TournamentFormat.SINGLE_ELIMINATION), 9001
        )
        assert olympic.format == TournamentFormat.SINGLE_ELIMINATION
        assert olympic.group_count is None

        group = TournamentService(db).create(
            payload(TournamentFormat.GROUP_PLAYOFF), 9001
        )
        assert group.format == TournamentFormat.GROUP_PLAYOFF
        assert group.group_count == 4
        assert group.qualifiers_per_group == 2
    finally:
        db.close()
        engine.dispose()


def test_format_settings_are_immutable_and_validated_at_creation():
    values = payload(TournamentFormat.SINGLE_ELIMINATION).model_dump()
    values["group_count"] = 4
    with pytest.raises(ValidationError):
        TournamentCreate(**values)

    values = payload(TournamentFormat.GROUP_PLAYOFF).model_dump()
    values["qualifiers_per_group"] = None
    with pytest.raises(ValidationError):
        TournamentCreate(**values)


def test_admin_approves_schedules_and_starts_olympic_tournament():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = service.create(payload(), 9001)
        players = [
            service.apply(tournament.id, telegram_id)
            for telegram_id in (101, 102)
        ]
        for seed, player in enumerate(players, start=1):
            reviewed = service.review(
                tournament.id,
                player.id,
                TournamentApplicationDecision(
                    decision="APPROVED",
                    seed=seed,
                ),
                9001,
            )
            assert reviewed.status == TournamentParticipantStatus.APPROVED

        with pytest.raises(TournamentServiceError):
            service.start(tournament.id)

        match = service.schedule_match(
            tournament.id,
            TournamentMatchSchedule(
                player_a_id=101,
                player_b_id=102,
                round_number=1,
                round_name="1/8 final",
                scheduled_at=tournament.starts_at + timedelta(hours=1),
            ),
            9001,
        )
        assert match.player_a_id == 101
        assert match.player_b_id == 102

        started = service.start(tournament.id)
        assert started.status == TournamentStatus.ACTIVE
        assert service.matches(tournament.id)[0].id == match.id
    finally:
        db.close()
        engine.dispose()


def test_group_match_requires_players_from_same_group():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = service.create(
            payload(TournamentFormat.GROUP_PLAYOFF), 9001
        )
        players = [
            service.apply(tournament.id, telegram_id)
            for telegram_id in (101, 102)
        ]
        for player, group_name in zip(players, ("A", "B")):
            service.review(
                tournament.id,
                player.id,
                TournamentApplicationDecision(
                    decision="APPROVED",
                    group_name=group_name,
                ),
                9001,
            )
        with pytest.raises(TournamentServiceError):
            service.schedule_match(
                tournament.id,
                TournamentMatchSchedule(
                    player_a_id=101,
                    player_b_id=102,
                    round_number=1,
                    round_name="Group A",
                    group_name="A",
                    scheduled_at=tournament.starts_at + timedelta(hours=1),
                ),
                9001,
            )
    finally:
        db.close()
        engine.dispose()
