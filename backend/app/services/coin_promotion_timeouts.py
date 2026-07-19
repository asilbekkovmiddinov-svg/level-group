import logging
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.core.config import COIN_PROMOTION_TIMEOUT_INTERVAL_SECONDS
from app.models.order import Order
from app.crud.order import cancel_order


logger = logging.getLogger(__name__)


def expire_once(session_factory: sessionmaker, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    discovery = session_factory()
    try:
        order_ids = [row[0] for row in discovery.query(Order.id).filter(
            Order.status.in_(("WAITING_OPERATOR", "CLAIMED")),
            Order.promotion_id.is_not(None),
            Order.expires_at.is_not(None),
            Order.expires_at <= now,
        ).order_by(Order.expires_at.asc(), Order.id.asc()).all()]
    finally:
        discovery.close()
    expired = 0
    for order_id in order_ids:
        db = session_factory()
        try:
            result = cancel_order(db, order_id, "Order timeout")
            if isinstance(result, Order):
                expired += 1
                logger.info("coin_promotion_order_timeout order_id=%s", order_id)
        except Exception:
            db.rollback()
            logger.exception("coin_promotion_order_timeout_failed order_id=%s", order_id)
        finally:
            db.close()
    return expired


class CoinPromotionTimeoutWorker:
    def __init__(self, session_factory: sessionmaker, interval_seconds=COIN_PROMOTION_TIMEOUT_INTERVAL_SECONDS):
        self.session_factory = session_factory
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="coin-promotion-timeouts", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.interval_seconds + 1, 5))

    def _run(self):
        while not self._stop.is_set():
            try:
                expire_once(self.session_factory)
            except Exception:
                logger.exception("coin_promotion_timeout_tick_failed")
            self._stop.wait(self.interval_seconds)
