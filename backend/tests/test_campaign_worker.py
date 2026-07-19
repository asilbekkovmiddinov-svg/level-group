import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.campaign import Campaign, CampaignRecipient
from app.models.promotion import Promotion
from app.models.user import User
from app.services import campaign_worker


TABLES = [User.__table__, Promotion.__table__, Campaign.__table__, CampaignRecipient.__table__]


def build_sessions():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine, expire_on_commit=False)


def seed(sessions, *, status="SCHEDULED", schedule_type="NOW", scheduled_at=None, audience="ALL_USERS"):
    db = sessions()
    db.add_all(User(telegram_id=value, first_name=f"User {value}", is_banned=False) for value in (101, 102, 103))
    campaign = Campaign(
        title="Worker campaign", message="Message", audience_type=audience,
        schedule_type=schedule_type, scheduled_at=scheduled_at, status=status,
        created_by=9001, updated_by=9001,
    )
    db.add(campaign)
    db.commit()
    campaign_id = campaign.id
    db.close()
    return campaign_id


def load(sessions, campaign_id):
    db = sessions()
    campaign = db.query(Campaign).filter_by(id=campaign_id).one()
    db.expunge(campaign)
    db.close()
    return campaign


def test_now_campaign_runs_immediately_and_logs_lifecycle(caplog):
    sessions = build_sessions()
    campaign_id = seed(sessions)
    with caplog.at_level(logging.INFO, logger="app.services.campaign_worker"):
        assert campaign_worker.run_once(sessions) == 1
    campaign = load(sessions, campaign_id)
    assert campaign.status == "COMPLETED"
    assert campaign.updated_by == 9001
    db = sessions()
    assert {item.user_id for item in db.query(CampaignRecipient).all()} == {101, 102, 103}
    db.close()
    assert "campaign_ready" in caplog.text
    assert "campaign_start" in caplog.text
    assert "campaign_complete" in caplog.text
    assert "recipient_count=3" in caplog.text
    assert "execution_seconds=" in caplog.text


def test_scheduled_campaign_waits_until_due():
    sessions = build_sessions()
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    campaign_id = seed(sessions, schedule_type="SCHEDULED", scheduled_at=due)
    assert campaign_worker.run_once(sessions, due - timedelta(seconds=1)) == 0
    assert load(sessions, campaign_id).status == "SCHEDULED"
    assert campaign_worker.run_once(sessions, due) == 1
    assert load(sessions, campaign_id).status == "COMPLETED"


def test_ready_and_running_campaigns_recover_after_restart():
    for status in ("READY", "RUNNING"):
        sessions = build_sessions()
        campaign_id = seed(sessions, status=status)
        db = sessions()
        db.add_all(CampaignRecipient(campaign_id=campaign_id, user_id=user_id) for user_id in (101, 102))
        db.commit()
        db.close()
        assert campaign_worker.run_once(sessions) == 1
        assert load(sessions, campaign_id).status == "COMPLETED"


def test_snapshot_is_idempotent_and_duplicates_are_never_created():
    sessions = build_sessions()
    campaign_id = seed(sessions)
    assert campaign_worker.run_once(sessions) == 1
    assert campaign_worker.run_once(sessions) == 0
    db = sessions()
    recipients = db.query(CampaignRecipient).filter_by(campaign_id=campaign_id).all()
    assert len(recipients) == 3
    assert len({item.user_id for item in recipients}) == 3
    db.close()


def test_statistics_are_finalized_from_recipient_snapshot():
    sessions = build_sessions()
    campaign_id = seed(sessions, status="RUNNING")
    db = sessions()
    db.add_all([
        CampaignRecipient(campaign_id=campaign_id, user_id=101, status="SENT"),
        CampaignRecipient(campaign_id=campaign_id, user_id=102, status="OPENED"),
        CampaignRecipient(campaign_id=campaign_id, user_id=103, status="FAILED"),
    ])
    db.commit()
    db.close()
    assert campaign_worker.run_once(sessions) == 1
    result = load(sessions, campaign_id)
    assert (result.sent_count, result.opened_count, result.clicked_count, result.failed_count) == (2, 1, 0, 1)


def test_only_one_worker_can_process_same_campaign(monkeypatch):
    sessions = build_sessions()
    campaign_id = seed(sessions)
    entered = threading.Event()
    release = threading.Event()
    original = campaign_worker._snapshot

    def delayed_snapshot(db, campaign):
        entered.set()
        release.wait(2)
        return original(db, campaign)

    monkeypatch.setattr(campaign_worker, "_snapshot", delayed_snapshot)
    first_result = []
    thread = threading.Thread(target=lambda: first_result.append(campaign_worker.run_once(sessions)))
    thread.start()
    assert entered.wait(1)
    assert campaign_worker.run_once(sessions) == 0
    release.set()
    thread.join(2)
    assert first_result == [1]
    assert load(sessions, campaign_id).status == "COMPLETED"


def test_invalid_automatic_audience_marks_campaign_failed(caplog):
    sessions = build_sessions()
    campaign_id = seed(sessions, audience="CUSTOM")
    with caplog.at_level(logging.ERROR, logger="app.services.campaign_worker"):
        assert campaign_worker.run_once(sessions) == 0
    assert load(sessions, campaign_id).status == "FAILED"
    assert "campaign_failed" in caplog.text


def test_periodic_worker_uses_configured_interval(monkeypatch):
    sessions = build_sessions()
    ticks = threading.Event()

    def tick(_sessions, now=None):
        ticks.set()
        return 0

    monkeypatch.setattr(campaign_worker, "run_once", tick)
    worker = campaign_worker.CampaignWorker(sessions, interval_seconds=0.01)
    worker.start()
    assert ticks.wait(1)
    worker.stop()
    assert worker._thread is not None and not worker._thread.is_alive()
