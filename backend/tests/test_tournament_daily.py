from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base
from app.models.tournament import (
    Tournament,
    TournamentDailyDelivery,
    TournamentEntryMode,
    TournamentFormat,
    TournamentGroupMode,
    TournamentParticipant,
    TournamentParticipantStatus,
    TournamentStatus,
)
from app.models.user import User
from app.services import tournament_daily


def build():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    now = datetime.now(timezone.utc)
    db.add_all([
        User(telegram_id=101, username="one", first_name="One"),
        User(telegram_id=102, username="two", first_name="Two"),
    ])
    tournament = Tournament(
        name="Daily Cup",
        format=TournamentFormat.GROUP_PLAYOFF,
        status=TournamentStatus.ACTIVE,
        max_participants=4,
        ticket_cost=2,
        entry_mode=TournamentEntryMode.COIN_PURCHASE,
        minimum_coin_purchase=300,
        duration_days=7,
        auto_start_when_full=True,
        announcement_channel_id="@level_results",
        group_count=1,
        group_size=4,
        group_mode=TournamentGroupMode.POINTS,
        qualifiers_per_group=2,
        registration_opens_at=now - timedelta(days=2),
        registration_closes_at=now - timedelta(days=1),
        starts_at=now - timedelta(days=1),
        ends_at=now + timedelta(days=6),
        created_by=9001,
    )
    db.add(tournament)
    db.flush()
    db.add_all([
        TournamentParticipant(
            tournament_id=tournament.id,
            telegram_id=101,
            status=TournamentParticipantStatus.APPROVED,
            points=6,
            played=2,
            wins=2,
        ),
        TournamentParticipant(
            tournament_id=tournament.id,
            telegram_id=102,
            status=TournamentParticipantStatus.APPROVED,
            points=3,
            played=2,
            wins=1,
            losses=1,
        ),
    ])
    db.commit()
    return db, engine, tournament


def test_daily_queue_is_idempotent_for_users_and_selected_channel():
    db, engine, tournament = build()
    try:
        now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
        assert tournament_daily.queue_daily_rankings(db, now=now) == 3
        assert tournament_daily.queue_daily_rankings(db, now=now) == 0
        rows = db.query(TournamentDailyDelivery).all()
        assert {(row.recipient_kind, row.recipient_id) for row in rows} == {
            ("USER", "101"),
            ("USER", "102"),
            ("CHANNEL", "@level_results"),
        }
    finally:
        db.close()
        engine.dispose()


def test_personal_and_channel_messages_show_current_ranking(monkeypatch):
    db, engine, tournament = build()
    sent = []

    class Result:
        message_id = 77

    monkeypatch.setattr(
        tournament_daily,
        "send_admin_message",
        lambda message, chat_id: sent.append((chat_id, message)) or Result(),
    )
    try:
        now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
        tournament_daily.queue_daily_rankings(db, now=now)
        while tournament_daily.process_next_daily_delivery(db, now) is not None:
            pass
        assert len(sent) == 3
        personal = next(message for target, message in sent if target == "101")
        channel = next(message for target, message in sent if target == "@level_results")
        assert "1-o‘rin / 2" in personal
        assert "@one — 6 ochko" in channel
        assert db.query(TournamentDailyDelivery).filter_by(status="SUCCESS").count() == 3
    finally:
        db.close()
        engine.dispose()
