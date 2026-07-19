import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import CAMPAIGN_WORKER_INTERVAL_SECONDS
from app.models.campaign import Campaign, CampaignRecipient
from app.schemas.campaign import CampaignExecutionRequest
from app.services.campaign_audience import select_audience
from app.services.campaign_execution import synchronize_statistics


logger = logging.getLogger(__name__)
_local_locks: dict[int, threading.Lock] = {}
_local_locks_guard = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _local_lock(campaign_id: int) -> threading.Lock:
    with _local_locks_guard:
        return _local_locks.setdefault(campaign_id, threading.Lock())


def due_campaign_ids(db: Session, now: datetime | None = None) -> list[int]:
    """Return runnable IDs; row locks are taken again in each isolated execution transaction."""
    now = now or utc_now()
    return [row[0] for row in (
        db.query(Campaign.id)
        .filter(Campaign.deleted_at.is_(None), or_(
            Campaign.status.in_(("READY", "RUNNING")),
            Campaign.status == "SCHEDULED",
        ))
        .filter(or_(
            Campaign.status.in_(("READY", "RUNNING")),
            Campaign.schedule_type == "NOW",
            Campaign.scheduled_at <= now,
        ))
        .order_by(Campaign.scheduled_at.asc(), Campaign.id.asc())
        .all()
    )]


def _locked_campaign(db: Session, campaign_id: int) -> Campaign | None:
    query = db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.deleted_at.is_(None))
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    else:
        query = query.with_for_update()
    return query.first()


def _is_due(campaign: Campaign, now: datetime) -> bool:
    if campaign.status in {"READY", "RUNNING"}:
        return True
    if campaign.status != "SCHEDULED":
        return False
    return campaign.schedule_type == "NOW" or (
        campaign.scheduled_at is not None and _as_utc(campaign.scheduled_at) <= now
    )


def _snapshot(db: Session, campaign: Campaign) -> int:
    existing = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).count()
    if existing:
        return existing
    user_ids = sorted(select_audience(db, campaign.audience_type, CampaignExecutionRequest()))
    db.add_all(CampaignRecipient(campaign_id=campaign.id, user_id=user_id) for user_id in user_ids)
    db.flush()
    return len(user_ids)


def process_campaign(db: Session, campaign_id: int, now: datetime | None = None) -> bool:
    """Run one campaign atomically; rollback makes interrupted executions safely retryable."""
    started = time.monotonic()
    now = now or utc_now()
    lock = _local_lock(campaign_id)
    if not lock.acquire(blocking=False):
        return False
    try:
        campaign = _locked_campaign(db, campaign_id)
        if campaign is None or not _is_due(campaign, now):
            db.rollback()
            return False
        recipient_count = db.query(CampaignRecipient).filter(CampaignRecipient.campaign_id == campaign.id).count()
        if campaign.status == "SCHEDULED":
            recipient_count = _snapshot(db, campaign)
            campaign.status = "READY"
            logger.info("campaign_ready campaign_id=%s recipient_count=%s", campaign.id, recipient_count)
        if campaign.status == "READY":
            campaign.status = "RUNNING"
            logger.info("campaign_start campaign_id=%s recipient_count=%s", campaign.id, recipient_count)
        if campaign.status == "RUNNING":
            synchronize_statistics(db, campaign)
            campaign.status = "COMPLETED"
            logger.info(
                "campaign_complete campaign_id=%s recipient_count=%s execution_seconds=%.6f",
                campaign.id, recipient_count, time.monotonic() - started,
            )
        db.commit()
        return True
    except Exception:
        db.rollback()
        try:
            failed = _locked_campaign(db, campaign_id)
            if failed is not None and failed.status not in {"CANCELLED", "DELETED", "COMPLETED"}:
                failed.status = "FAILED"
                db.commit()
        except Exception:
            db.rollback()
        logger.exception("campaign_failed campaign_id=%s execution_seconds=%.6f", campaign_id, time.monotonic() - started)
        return False
    finally:
        lock.release()


def run_once(session_factory: sessionmaker, now: datetime | None = None) -> int:
    discovery = session_factory()
    try:
        campaign_ids = due_campaign_ids(discovery, now)
    finally:
        discovery.close()
    completed = 0
    for campaign_id in campaign_ids:
        db = session_factory()
        try:
            completed += int(process_campaign(db, campaign_id, now))
        finally:
            db.close()
    return completed


class CampaignWorker:
    def __init__(self, session_factory: sessionmaker, interval_seconds: float = CAMPAIGN_WORKER_INTERVAL_SECONDS):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="campaign-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.interval_seconds + 1, 5))

    def _run(self) -> None:
        logger.info("campaign_worker_started interval_seconds=%s", self.interval_seconds)
        while not self._stop.is_set():
            try:
                run_once(self.session_factory)
            except Exception:
                logger.exception("campaign_worker_tick_failed")
            self._stop.wait(self.interval_seconds)
        logger.info("campaign_worker_stopped")
