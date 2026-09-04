from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.tournament_migrations import run_tournament_migrations
from app.models.arena_v3 import ArenaV3Match
from app.models.tournament import (
    Tournament,
    TournamentDailyDelivery,
    TournamentEntryMode,
    TournamentFormat,
    TournamentGroupMode,
    TournamentMatch,
    TournamentMatchStatus,
    TournamentParticipant,
    TournamentParticipantStatus,
    TournamentStatus,
)
from app.models.user import User
from app.models.wall_rush import GameTicketWallet
from app.schemas.tournament import (
    TournamentCreate,
    TournamentManualResult,
    TournamentMatchSchedule,
)
from app.services.tournament import TournamentService, TournamentServiceError


PLAYER_IDS = tuple(range(101, 109))


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
            GameTicketWallet.__table__,
            ArenaV3Match.__table__,
            Tournament.__table__,
            TournamentParticipant.__table__,
            TournamentMatch.__table__,
            TournamentDailyDelivery.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add(User(telegram_id=9001, username="admin", first_name="Admin"))
    db.add_all([
        User(
            telegram_id=telegram_id,
            username=f"player{telegram_id}",
            first_name=f"Player {telegram_id}",
        )
        for telegram_id in PLAYER_IDS
    ])
    db.add_all([
        GameTicketWallet(telegram_id=telegram_id, tournament_tickets=50)
        for telegram_id in PLAYER_IDS
    ])
    db.commit()
    return db, engine


def payload(
    *,
    name="Simple LEVEL Cup",
    mode=TournamentGroupMode.POINTS,
    max_participants=8,
    group_size=4,
    ticket_cost=7,
    entry_mode=TournamentEntryMode.TICKET,
    duration_days=7,
    announcement_channel_id=None,
):
    now = datetime.now(timezone.utc)
    return TournamentCreate(
        name=name,
        format=TournamentFormat.GROUP_PLAYOFF,
        max_participants=max_participants,
        ticket_cost=ticket_cost,
        entry_mode=entry_mode,
        minimum_coin_purchase=300,
        duration_days=duration_days,
        announcement_channel_id=announcement_channel_id,
        group_size=group_size,
        group_mode=mode,
        qualifiers_per_group=2,
        registration_opens_at=now - timedelta(hours=1),
        registration_closes_at=now + timedelta(hours=1),
        starts_at=now + timedelta(hours=2),
        ends_at=now + timedelta(days=7),
    )


def join_all(service, tournament):
    return [
        service.apply(tournament.id, telegram_id)
        for telegram_id in PLAYER_IDS[: tournament.max_participants]
    ]


def start_simple_tournament(service, mode=TournamentGroupMode.POINTS):
    tournament = service.create(payload(mode=mode), 9001)
    join_all(service, tournament)
    return service.start(tournament.id, 9001)


def test_admin_configures_entry_ticket_group_size_mode_and_qualifiers():
    points = payload(mode=TournamentGroupMode.POINTS)
    elimination = payload(mode=TournamentGroupMode.ELIMINATION)

    assert points.ticket_cost == 7
    assert points.group_size == 4
    assert points.group_count == 2
    assert points.qualifiers_per_group == 2
    assert elimination.group_mode == TournamentGroupMode.ELIMINATION


def test_migration_adds_simple_group_fields_and_preserves_entry_ticket_price():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE tournaments (id INTEGER PRIMARY KEY, "
                "format VARCHAR(32), max_participants INTEGER, ticket_cost INTEGER, "
                "group_count INTEGER, qualifiers_per_group INTEGER)"
            ))
            connection.execute(text(
                "CREATE TABLE tournament_participants (id INTEGER PRIMARY KEY, "
                "tournament_id INTEGER, telegram_id BIGINT, status VARCHAR(32), "
                "seed INTEGER, group_name VARCHAR(16), played INTEGER DEFAULT 0, "
                "wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0, points INTEGER DEFAULT 0, "
                "advanced_round INTEGER DEFAULT 0, applied_at TIMESTAMP, "
                "reviewed_at TIMESTAMP, reviewed_by BIGINT)"
            ))
            connection.execute(text(
                "INSERT INTO tournaments "
                "(id, format, max_participants, ticket_cost, group_count, qualifiers_per_group) "
                "VALUES (1, 'GROUP_PLAYOFF', 16, 7, 4, 2)"
            ))

        run_tournament_migrations(engine)

        tournament_columns = {
            column["name"] for column in inspect(engine).get_columns("tournaments")
        }
        participant_columns = {
            column["name"]
            for column in inspect(engine).get_columns("tournament_participants")
        }
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT ticket_cost, group_size, group_mode FROM tournaments WHERE id = 1"
            )).one()
        assert tournament_columns >= {"group_size", "group_mode"}
        assert participant_columns >= {
            "entry_ticket_state", "goals_for", "goals_against"
        }
        assert tuple(row) == (7, 4, "POINTS")
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_participants", 10),
        ("qualifiers_per_group", 4),
        ("group_size", None),
        ("group_mode", None),
    ],
)
def test_invalid_group_settings_are_rejected(field, value):
    values = payload().model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        TournamentCreate(**values)


def test_join_spends_configurable_entry_ticket_once_and_auto_approves():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = service.create(payload(ticket_cost=7), 9001)

        participant = service.apply(tournament.id, 101)
        repeated = service.apply(tournament.id, 101)

        assert participant.id == repeated.id
        assert participant.status == TournamentParticipantStatus.APPROVED
        assert participant.entry_ticket_state == "SPENT"
        assert db.get(GameTicketWallet, 101).tournament_tickets == 43
    finally:
        db.close()
        engine.dispose()


def test_join_requires_entry_ticket_and_capacity():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = service.create(
            payload(max_participants=4, group_size=4, ticket_cost=10),
            9001,
        )
        db.get(GameTicketWallet, 101).tournament_tickets = 9
        db.commit()
        with pytest.raises(TournamentServiceError, match="kamida 10 ta"):
            service.apply(tournament.id, 101)

        db.get(GameTicketWallet, 101).tournament_tickets = 10
        db.commit()
        for telegram_id in (101, 102, 103, 104):
            service.apply(tournament.id, telegram_id)
        with pytest.raises(TournamentServiceError, match="capacity"):
            service.apply(tournament.id, 105)
    finally:
        db.close()
        engine.dispose()


def test_start_requires_all_places_and_assigns_four_player_groups():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = service.create(payload(), 9001)
        for telegram_id in PLAYER_IDS[:7]:
            service.apply(tournament.id, telegram_id)
        with pytest.raises(TournamentServiceError, match="8 ta joy"):
            service.start(tournament.id, 9001)

        service.apply(tournament.id, PLAYER_IDS[7])
        started = service.start(tournament.id, 9001)
        participants = service.public_participants(tournament.id)

        assert started.status == TournamentStatus.ACTIVE
        assert [row.group_name for row in participants] == ["A"] * 4 + ["B"] * 4
        assert [row.seed for row in participants] == list(range(1, 9))
    finally:
        db.close()
        engine.dispose()


def test_single_300_coin_purchase_registers_and_auto_starts_when_full():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = service.create(payload(
            max_participants=4,
            group_size=4,
            ticket_cost=2,
            entry_mode=TournamentEntryMode.COIN_PURCHASE,
            duration_days=12,
        ), 9001)
        assert tournament.starts_at is None
        assert tournament.ends_at is None

        for index, telegram_id in enumerate(PLAYER_IDS[:4], start=1):
            rows = service.auto_register_coin_purchase(SimpleNamespace(
                id=1000 + index,
                telegram_id=telegram_id,
                product_type="COIN",
                coins_amount=300,
            ))
            assert len(rows) == 1

        db.commit()
        db.refresh(tournament)
        assert tournament.status == TournamentStatus.ACTIVE
        assert tournament.starts_at is not None
        assert tournament.ends_at - tournament.starts_at == timedelta(days=12)
        participants = service.public_participants(tournament.id)
        assert len(participants) == 4
        assert {row.entry_ticket_state for row in participants} == {"COIN_PURCHASE"}
        assert {row.qualification_coin_amount for row in participants} == {300}
        assert all(db.get(GameTicketWallet, row.telegram_id).tournament_tickets == 50
                   for row in participants)
    finally:
        db.close()
        engine.dispose()


def test_small_or_split_coin_purchases_do_not_qualify_and_duplicate_is_ignored():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = service.create(payload(
            max_participants=4,
            group_size=4,
            entry_mode=TournamentEntryMode.COIN_PURCHASE,
        ), 9001)
        for order_id, amount in ((1, 150), (2, 150)):
            assert service.auto_register_coin_purchase(SimpleNamespace(
                id=order_id, telegram_id=101, product_type="COIN", coins_amount=amount,
            )) == []
        first = service.auto_register_coin_purchase(SimpleNamespace(
            id=3, telegram_id=101, product_type="COIN", coins_amount=300,
        ))
        repeated = service.auto_register_coin_purchase(SimpleNamespace(
            id=4, telegram_id=101, product_type="COIN", coins_amount=840,
        ))
        db.commit()
        assert len(first) == 1
        assert repeated == []
        assert service.participant_count(tournament.id) == 1
    finally:
        db.close()
        engine.dispose()


def test_finished_tournament_keeps_final_standings_and_multiple_tournaments_list():
    db, engine = build()
    try:
        service = TournamentService(db)
        first = service.create(payload(name="First Cup"), 9001)
        second_values = payload().model_dump()
        second_values["name"] = "Second Cup"
        second = service.create(TournamentCreate(**second_values), 9001)
        assert {row.id for row in service.list_tournaments()} >= {first.id, second.id}

        join_all(service, first)
        service.start(first.id, 9001)
        first.ends_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        service.finish_due()

        assert first.status == TournamentStatus.FINISHED
        assert service.participant_count(first.id) == len(PLAYER_IDS)
        assert len(service.standings(first.id)) == len(PLAYER_IDS)
    finally:
        db.close()
        engine.dispose()


def test_admin_schedules_each_group_match_time_and_blocks_cross_group_pair():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = start_simple_tournament(service)
        scheduled_at = tournament.starts_at + timedelta(hours=1)

        match = service.schedule_match(
            tournament.id,
            TournamentMatchSchedule(
                player_a_id=101,
                player_b_id=102,
                round_number=1,
                round_name="Guruh A",
                group_name="A",
                scheduled_at=scheduled_at,
            ),
            9001,
        )
        assert match.status == TournamentMatchStatus.SCHEDULED
        assert match.scheduled_at == scheduled_at

        with pytest.raises(TournamentServiceError, match="already have a match"):
            service.schedule_match(
                tournament.id,
                TournamentMatchSchedule(
                    player_a_id=102,
                    player_b_id=101,
                    round_number=1,
                    round_name="Guruh A",
                    group_name="A",
                    scheduled_at=scheduled_at + timedelta(hours=1),
                ),
                9001,
            )

        with pytest.raises(TournamentServiceError, match="share group"):
            service.schedule_match(
                tournament.id,
                TournamentMatchSchedule(
                    player_a_id=101,
                    player_b_id=105,
                    round_number=1,
                    round_name="Guruh A",
                    group_name="A",
                    scheduled_at=scheduled_at,
                ),
                9001,
            )
    finally:
        db.close()
        engine.dispose()


def test_points_result_updates_table_and_edit_reverses_old_statistics():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = start_simple_tournament(service)
        match = service.schedule_match(
            tournament.id,
            TournamentMatchSchedule(
                player_a_id=101,
                player_b_id=102,
                round_number=1,
                round_name="Guruh A",
                group_name="A",
                scheduled_at=tournament.starts_at,
            ),
            9001,
        )

        service.record_result(
            tournament.id,
            match.id,
            TournamentManualResult(player_a_score=3, player_b_score=1),
            9001,
        )
        alpha = service.participant(tournament.id, 101)
        beta = service.participant(tournament.id, 102)
        assert (alpha.played, alpha.wins, alpha.points) == (1, 1, 3)
        assert (alpha.goals_for, alpha.goals_against) == (3, 1)
        assert (beta.played, beta.losses, beta.points) == (1, 1, 0)

        service.record_result(
            tournament.id,
            match.id,
            TournamentManualResult(player_a_score=0, player_b_score=2),
            9001,
        )
        db.refresh(alpha)
        db.refresh(beta)
        assert (alpha.played, alpha.wins, alpha.losses, alpha.points) == (1, 0, 1, 0)
        assert (alpha.goals_for, alpha.goals_against) == (0, 2)
        assert (beta.played, beta.wins, beta.losses, beta.points) == (1, 1, 0, 3)
    finally:
        db.close()
        engine.dispose()


def test_elimination_result_marks_loser_out_without_extra_ticket_charge():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = start_simple_tournament(
            service, mode=TournamentGroupMode.ELIMINATION
        )
        before = db.get(GameTicketWallet, 101).tournament_tickets
        match = service.schedule_match(
            tournament.id,
            TournamentMatchSchedule(
                player_a_id=101,
                player_b_id=102,
                round_number=1,
                round_name="Guruh A · 1-bosqich",
                group_name="A",
                scheduled_at=tournament.starts_at,
            ),
            9001,
        )

        result = service.record_result(
            tournament.id,
            match.id,
            TournamentManualResult(player_a_score=2, player_b_score=1),
            9001,
        )

        assert result.winner_id == 101
        assert service.participant(tournament.id, 101).status == "APPROVED"
        assert service.participant(tournament.id, 102).status == "ELIMINATED"
        assert db.get(GameTicketWallet, 101).tournament_tickets == before
    finally:
        db.close()
        engine.dispose()


def test_manual_result_requires_a_winner():
    with pytest.raises(ValidationError):
        TournamentManualResult(player_a_score=2, player_b_score=2)


def test_finalize_points_groups_keeps_configured_top_players():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = start_simple_tournament(service)
        for group_name in ("A", "B"):
            rows = service.public_participants(
                tournament.id, group_name=group_name
            )
            for index, row in enumerate(rows):
                row.played = 3
                row.wins = 3 - index
                row.losses = index
                row.points = (3 - index) * 3
                row.goals_for = 9 - index
                row.goals_against = index
        db.commit()

        result = service.finalize_groups(tournament.id)

        assert result == {
            "groups_finalized": 2,
            "qualified_players": 4,
            "eliminated_players": 4,
        }
        approved = service.applications(
            tournament.id, TournamentParticipantStatus.APPROVED
        )
        assert {row.telegram_id for row in approved} == {101, 102, 105, 106}
    finally:
        db.close()
        engine.dispose()


def test_finalize_groups_requires_all_results_and_complete_round_robin():
    db, engine = build()
    try:
        service = TournamentService(db)
        tournament = start_simple_tournament(service)
        match = service.schedule_match(
            tournament.id,
            TournamentMatchSchedule(
                player_a_id=101,
                player_b_id=102,
                round_number=1,
                round_name="Guruh A",
                group_name="A",
                scheduled_at=tournament.starts_at,
            ),
            9001,
        )
        with pytest.raises(TournamentServiceError, match="results must be entered"):
            service.finalize_groups(tournament.id)

        service.record_result(
            tournament.id,
            match.id,
            TournamentManualResult(player_a_score=1, player_b_score=0),
            9001,
        )
        with pytest.raises(TournamentServiceError, match="round-robin matches"):
            service.finalize_groups(tournament.id)
    finally:
        db.close()
        engine.dispose()
