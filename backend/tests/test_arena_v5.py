from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.arena_internal_auth import require_arena_internal_api_key
from app.models import *  # noqa: F401,F403 - register full metadata for FK resolution
from app.models.arena_v3 import (
    ArenaV3Stats,
    ArenaV3Status,
    ArenaV5QueueEntry,
    ArenaV5ScreenshotSubmission,
)
from app.models.arena_v5_season import (
    ArenaV5ReferralPoint,
    ArenaV5Season,
    ArenaV5SeasonStatus,
)
from app.models.referral import ReferralProfile
from app.models.user import User
from app.models.wall_rush import GameTicketLedger, GameTicketWallet
from app.models.wallet import Wallet
from app.services.arena_v3 import ArenaV3Conflict, ArenaV3Forbidden
from app.services.arena_v4_admin_review import ArenaV4AdminReviewService
from app.services.arena_v5 import ArenaV5Service
from app.services.arena_v5_seasons import ArenaV5SeasonService
from app.services.referrals import attach_registration_referral
from app.routers.arena_v5 import internal_router


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    now = datetime.now(timezone.utc)
    session.add_all([
        User(
            telegram_id=101,
            username="alpha_tg",
            first_name="Alpha",
            efootball_username="ALPHA FC",
        ),
        ArenaV5Season(
            name="Sinov Arena",
            status=ArenaV5SeasonStatus.ACTIVE,
            duration_days=7,
            points_for_win=3,
            points_for_draw=1,
            points_for_loss=0,
            referral_points=3,
            starts_at=now - timedelta(hours=1),
            ends_at=now + timedelta(days=7),
            created_by=9001,
        ),
        User(
            telegram_id=202,
            username="beta_tg",
            first_name="Beta",
            efootball_username="BETA FC",
        ),
        User(
            telegram_id=303,
            username="outsider",
            first_name="Other",
            efootball_username="OTHER FC",
        ),
        GameTicketWallet(telegram_id=101, tournament_tickets=2),
        GameTicketWallet(telegram_id=202, tournament_tickets=2),
        GameTicketWallet(telegram_id=303, tournament_tickets=2),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _matched(db):
    service = ArenaV5Service(db)
    waiting = service.join_queue(101, "queue-alpha")
    assert waiting["state"] == "SEARCHING"
    paired = service.join_queue(202, "queue-beta")
    assert paired["state"] == "MATCHED"
    return service, paired["match"]


def test_every_v5_bot_route_requires_internal_auth():
    assert internal_router.routes
    for route in internal_router.routes:
        dependencies = {item.call for item in route.dependant.dependencies}
        assert require_arena_internal_api_key in dependencies


def test_matchmaking_spends_one_ticket_only_after_pairing(db):
    service = ArenaV5Service(db)
    waiting = service.join_queue(101, "queue-alpha")
    assert waiting["ticket_balance"] == 2
    assert db.get(GameTicketWallet, 101).tournament_tickets == 2

    paired = service.join_queue(202, "queue-beta")
    match = paired["match"]
    assert paired["matched_now"] is True
    assert match["player_a"]["telegram_id"] == 101
    assert match["player_b"]["telegram_id"] == 202
    assert db.get(GameTicketWallet, 101).tournament_tickets == 1
    assert db.get(GameTicketWallet, 202).tournament_tickets == 1
    assert db.get(ArenaV5QueueEntry, 101) is None
    ledgers = db.execute(
        select(GameTicketLedger).where(
            GameTicketLedger.operation == "ARENA_V5_ENTRY"
        )
    ).scalars().all()
    assert len(ledgers) == 2
    assert {row.amount for row in ledgers} == {-1}
    assert service.repository.get_match(match["id"]).arena_v5_season_id is not None


def test_duplicate_queue_and_cancel_are_idempotent_without_ticket_loss(db):
    service = ArenaV5Service(db)
    first = service.join_queue(101, "queue-alpha")
    second = service.join_queue(101, "queue-alpha-retry")
    assert first["state"] == second["state"] == "SEARCHING"
    assert db.query(ArenaV5QueueEntry).count() == 1
    assert service.cancel_queue(101)["state"] == "IDLE"
    assert service.cancel_queue(101)["state"] == "IDLE"
    assert db.get(GameTicketWallet, 101).tournament_tickets == 2


def test_active_player_cannot_queue_or_create_a_second_match(db):
    service, match_data = _matched(db)
    repeated = service.join_queue(101, "queue-alpha-second-match")
    assert repeated["state"] == "MATCHED"
    assert repeated["match"]["id"] == match_data["id"]
    assert db.get(ArenaV5QueueEntry, 101) is None
    assert db.get(GameTicketWallet, 101).tournament_tickets == 1


def test_relay_token_is_participant_bound_and_finished_state_closes_relay(db):
    service, match_data = _matched(db)
    token = match_data["bot_deep_link"].split("arena_", 1)[1]
    assert service.validate_relay(101, token)["opponent_telegram_id"] == 202
    with pytest.raises(ArenaV3Forbidden):
        service.validate_relay(303, token)

    match = service.repository.get_match(match_data["id"])
    match.status = ArenaV3Status.FINISHED
    db.commit()
    with pytest.raises(ArenaV3Conflict):
        service.validate_relay(101, token)


def test_screenshot_submission_is_minimal_idempotent_and_moves_to_admin(db):
    service, match_data = _matched(db)
    prepared = service.prepare_submission(
        player_id=101,
        telegram_file_id="telegram-photo-id",
        telegram_message_id=55,
    )
    assert prepared["should_deliver"] is True
    assert db.query(ArenaV5ScreenshotSubmission).count() == 1

    completed = service.complete_submission(prepared["submission_id"], 999)
    assert completed["delivery_status"] == "SENT"
    assert completed["should_deliver"] is False
    assert service.repository.get_match(match_data["id"]).status == ArenaV3Status.WAITING_ADMIN

    duplicate = service.prepare_submission(
        player_id=101,
        telegram_file_id="telegram-photo-id",
        telegram_message_id=55,
    )
    assert duplicate["should_deliver"] is False
    assert db.query(ArenaV5ScreenshotSubmission).count() == 1


def test_admin_draw_settles_once_and_awards_one_point_each(db):
    service, match_data = _matched(db)
    prepared = service.prepare_submission(
        player_id=101,
        telegram_file_id="photo",
        telegram_message_id=60,
    )
    service.complete_submission(prepared["submission_id"], 1000)

    admin = ArenaV4AdminReviewService(db)
    review = admin.claim_channel_review(match_id=match_data["id"], admin_id=9001)
    payload = SimpleNamespace(
        owner_score=2,
        opponent_score=2,
        reason="ARENA_V5_TEST",
        allow_draw=True,
    )
    decided = admin.submit_decision(
        review_id=review.id,
        admin_id=9001,
        payload=payload,
        idempotency_key="draw-result-once",
    )
    replay = admin.submit_decision(
        review_id=review.id,
        admin_id=9001,
        payload=payload,
        idempotency_key="draw-result-once",
    )
    assert replay.id == decided.id
    match = service.repository.get_match(match_data["id"])
    assert match.status == ArenaV3Status.FINISHED
    assert match.winner_id is None
    assert db.get(ArenaV3Stats, 101).draws == 1
    assert db.get(ArenaV3Stats, 202).draws == 1
    assert db.get(ArenaV3Stats, 101).points == 1
    assert db.get(ArenaV3Stats, 202).points == 1


def test_win_updates_points_ranking_and_player_history(db):
    service, match_data = _matched(db)
    prepared = service.prepare_submission(
        player_id=101,
        telegram_file_id="winner-photo",
        telegram_message_id=65,
    )
    service.complete_submission(prepared["submission_id"], 1002)

    admin = ArenaV4AdminReviewService(db)
    review = admin.claim_channel_review(match_id=match_data["id"], admin_id=9001)
    admin.submit_decision(
        review_id=review.id,
        admin_id=9001,
        payload=SimpleNamespace(
            owner_score=3,
            opponent_score=1,
            reason="ARENA_V5_WIN_TEST",
            allow_draw=True,
        ),
        idempotency_key="win-result-once",
    )

    assert db.get(ArenaV3Stats, 101).points == 3
    assert db.get(ArenaV3Stats, 202).points == 0
    ranking = service.ranking(limit=10, offset=0)
    assert [item["efootball_username"] for item in ranking["players"]] == [
        "ALPHA FC",
        "BETA FC",
    ]
    assert [item["points"] for item in ranking["players"]] == [3, 0]
    assert ranking["players"][0]["match_points"] == 3
    assert ranking["players"][0]["referral_points"] == 0
    owner_history = service.history(101, limit=10, offset=0)
    opponent_history = service.history(202, limit=10, offset=0)
    assert owner_history[0]["result"] == "WIN"
    assert owner_history[0]["points"] == 3
    assert owner_history[0]["season_id"] == ranking["season_id"]
    assert opponent_history[0]["result"] == "LOSS"
    assert opponent_history[0]["points"] == 0

    seasons = ArenaV5SeasonService(db)
    old_season = seasons.finish(ranking["season_id"])
    new_season = seasons.create(
        name="Keyingi Arena",
        duration_days=5,
        created_by=9001,
    )
    summaries = service.season_history(101)
    assert [item["season_id"] for item in summaries] == [new_season.id, old_season.id]
    assert summaries[0]["games_played"] == 0
    assert summaries[0]["points"] == 0
    assert summaries[1]["games_played"] == 1
    assert summaries[1]["wins"] == 1
    assert summaries[1]["goals_for"] == 3
    assert summaries[1]["match_points"] == 3
    assert summaries[1]["referral_points"] == 0
    assert summaries[1]["points"] == 3
    assert service.history(
        101, limit=10, offset=0, season_id=new_season.id
    ) == []


def test_admin_controls_duration_and_archives_each_season(db):
    seasons = ArenaV5SeasonService(db)
    active = seasons.active()
    updated = seasons.update_duration(active.id, duration_days=14)
    assert updated.duration_days == 14
    assert updated.ends_at - updated.starts_at == timedelta(days=14)
    finished = seasons.finish(active.id)
    assert finished.status == ArenaV5SeasonStatus.FINISHED

    created = seasons.create(
        name="30 kunlik Arena",
        duration_days=30,
        created_by=9001,
        prize_text="Top 3 sovrin oladi",
    )
    assert created.duration_days == 30
    assert created.status == ArenaV5SeasonStatus.ACTIVE
    assert created.ends_at - created.starts_at == timedelta(days=30)
    assert len(seasons.list()) == 2


def test_closed_arena_blocks_new_matchmaking(db):
    seasons = ArenaV5SeasonService(db)
    seasons.finish(seasons.active().id)
    with pytest.raises(ArenaV3Conflict, match="faol Arena mavsumi yo‘q"):
        ArenaV5Service(db).join_queue(101, "closed-arena")


def test_real_referral_awards_three_points_only_in_active_season(db, monkeypatch):
    monkeypatch.setattr("app.services.referrals.config.REFERRALS_ENABLED", True)
    db.add_all([
        User(telegram_id=404, username="new_user", first_name="New"),
        Wallet(telegram_id=101, uzs_balance=0, efc_balance=0),
        ReferralProfile(telegram_id=101, referral_code="ALPHA-REF"),
    ])
    db.commit()

    referral = attach_registration_referral(db, 404, "ALPHA-REF")
    db.commit()
    assert referral is not None
    award = db.query(ArenaV5ReferralPoint).one()
    assert award.points == 3
    assert award.referrer_telegram_id == 101

    ranking = ArenaV5Service(db).ranking(limit=10, offset=0)
    assert ranking["players"][0]["telegram_id"] == 101
    assert ranking["players"][0]["referral_count"] == 1
    assert ranking["players"][0]["referral_points"] == 3
    assert ranking["players"][0]["points"] == 3
    profile = ArenaV5Service(db).profile(101)
    assert profile["referral_count"] == 1
    assert profile["points"] == 3
    season_result = ArenaV5Service(db).season_history(101)[0]
    assert season_result["games_played"] == 0
    assert season_result["referral_count"] == 1
    assert season_result["referral_points"] == 3
    assert season_result["points"] == 3


def test_admin_cancel_refunds_each_ticket_exactly_once(db):
    service, match_data = _matched(db)
    prepared = service.prepare_submission(
        player_id=202,
        telegram_file_id="cancel-photo",
        telegram_message_id=70,
    )
    service.complete_submission(prepared["submission_id"], 1001)

    admin = ArenaV4AdminReviewService(db)
    review = admin.claim_channel_review(match_id=match_data["id"], admin_id=9001)
    payload = SimpleNamespace(reason="TECHNICAL_ISSUE")
    first = admin.submit_cancel(
        review_id=review.id,
        admin_id=9001,
        payload=payload,
        idempotency_key="cancel-once",
    )
    replay = admin.submit_cancel(
        review_id=review.id,
        admin_id=9001,
        payload=payload,
        idempotency_key="cancel-once",
    )
    assert replay.id == first.id
    assert db.get(GameTicketWallet, 101).tournament_tickets == 2
    assert db.get(GameTicketWallet, 202).tournament_tickets == 2
    refunds = db.execute(
        select(GameTicketLedger).where(
            GameTicketLedger.operation == "ARENA_V5_REFUND"
        )
    ).scalars().all()
    assert len(refunds) == 2
    assert db.get(ArenaV3Stats, 101) is None
    assert db.get(ArenaV3Stats, 202) is None
