from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_

from app.core import config
from app.models.tournament import (
    Tournament,
    TournamentDailyDelivery,
    TournamentParticipant,
    TournamentParticipantStatus,
    TournamentStatus,
)
from app.services.telegram_notifications import (
    TelegramNotificationPermanentError,
    send_admin_message,
)
from app.services.tournament import TournamentService, as_utc, utc_now


logger = logging.getLogger(__name__)
ACTIVE_PARTICIPANT_STATUSES = (
    TournamentParticipantStatus.APPROVED,
    TournamentParticipantStatus.ELIMINATED,
)


def _remaining(ends_at: datetime | None, now: datetime) -> str:
    if ends_at is None:
        return "—"
    seconds = max(0, int((as_utc(ends_at) - now).total_seconds()))
    days, seconds = divmod(seconds, 86400)
    hours, _ = divmod(seconds, 3600)
    return f"{days} kun {hours} soat"


def _display_name(participant: TournamentParticipant) -> str:
    user = participant.user
    if user is None:
        return str(participant.telegram_id)
    return user.username or user.first_name or str(participant.telegram_id)


def _ranked(service: TournamentService, tournament_id: int):
    return service.standings(tournament_id)


def personal_ranking_message(
    service: TournamentService,
    tournament: Tournament,
    participant: TournamentParticipant,
    now: datetime,
) -> str:
    rows = _ranked(service, tournament.id)
    rank = next(
        (index for index, row in enumerate(rows, start=1) if row.id == participant.id),
        len(rows),
    )
    return (
        f"🏆 {tournament.name}\n\n"
        f"Bugungi reytingingiz: {rank}-o‘rin / {len(rows)}\n"
        f"Ochko: {participant.points}\n"
        f"O‘yin: {participant.played} | G‘alaba: {participant.wins} | "
        f"Mag‘lubiyat: {participant.losses}\n"
        f"Tugashiga: {_remaining(tournament.ends_at, now)}"
    )


def channel_ranking_message(
    service: TournamentService,
    tournament: Tournament,
    now: datetime,
) -> str:
    rows = _ranked(service, tournament.id)
    lines = [
        f"🏆 {tournament.name} — kunlik reyting",
        "",
    ]
    for index, row in enumerate(rows[:50], start=1):
        name = _display_name(row)
        prefix = "@" if row.user and row.user.username else ""
        lines.append(
            f"{index}. {prefix}{name} — {row.points} ochko "
            f"({row.played} o‘yin, {row.wins} g‘alaba)"
        )
    if not rows:
        lines.append("Reyting hali shakllanmagan.")
    lines.extend(("", f"Tugashiga: {_remaining(tournament.ends_at, now)}"))
    return "\n".join(lines)[:4000]


def queue_daily_rankings(
    db,
    *,
    now: datetime | None = None,
    delivery_date: date | None = None,
) -> int:
    value = as_utc(now or utc_now())
    local_date = delivery_date or value.astimezone(
        ZoneInfo(config.TOURNAMENT_TIMEZONE)
    ).date()
    tournaments = (
        db.query(Tournament)
        .filter(Tournament.status == TournamentStatus.ACTIVE)
        .order_by(Tournament.id)
        .all()
    )
    created = 0
    for tournament in tournaments:
        participants = (
            db.query(TournamentParticipant)
            .filter(
                TournamentParticipant.tournament_id == tournament.id,
                TournamentParticipant.status.in_(ACTIVE_PARTICIPANT_STATUSES),
            )
            .all()
        )
        recipients = [("USER", str(row.telegram_id)) for row in participants]
        if tournament.announcement_channel_id:
            recipients.append(("CHANNEL", tournament.announcement_channel_id))
        for kind, recipient_id in recipients:
            exists = (
                db.query(TournamentDailyDelivery.id)
                .filter_by(
                    tournament_id=tournament.id,
                    delivery_date=local_date,
                    recipient_kind=kind,
                    recipient_id=recipient_id,
                )
                .first()
            )
            if exists:
                continue
            db.add(TournamentDailyDelivery(
                tournament_id=tournament.id,
                delivery_date=local_date,
                recipient_kind=kind,
                recipient_id=recipient_id,
            ))
            created += 1
    if created:
        db.commit()
    return created


def _claim(db, now: datetime):
    stale = now - timedelta(seconds=config.TOURNAMENT_DELIVERY_CLAIM_TTL_SECONDS)
    delivery = (
        db.query(TournamentDailyDelivery)
        .filter(
            TournamentDailyDelivery.attempts
            < config.TOURNAMENT_DELIVERY_MAX_ATTEMPTS,
            or_(
                TournamentDailyDelivery.status.in_(("PENDING", "FAILED")),
                (
                    (TournamentDailyDelivery.status == "SENDING")
                    & (TournamentDailyDelivery.last_attempt_at < stale)
                ),
            ),
        )
        .order_by(TournamentDailyDelivery.created_at, TournamentDailyDelivery.id)
        .with_for_update(skip_locked=True)
        .first()
    )
    if delivery is None:
        db.rollback()
        return None
    delivery.status = "SENDING"
    delivery.attempts += 1
    delivery.last_attempt_at = now
    delivery.last_error = None
    delivery_id, attempt = delivery.id, delivery.attempts
    db.commit()
    return delivery_id, attempt


def process_next_daily_delivery(db, now: datetime | None = None) -> bool | None:
    value = as_utc(now or utc_now())
    claimed = _claim(db, value)
    if claimed is None:
        return None
    delivery_id, attempt = claimed
    delivery = db.get(TournamentDailyDelivery, delivery_id)
    tournament = db.get(Tournament, delivery.tournament_id) if delivery else None
    try:
        if delivery is None or tournament is None:
            raise RuntimeError("Tournament delivery source is missing")
        service = TournamentService(db)
        if delivery.recipient_kind == "USER":
            participant = (
                db.query(TournamentParticipant)
                .filter_by(
                    tournament_id=tournament.id,
                    telegram_id=int(delivery.recipient_id),
                )
                .one()
            )
            message = personal_ranking_message(service, tournament, participant, value)
        else:
            message = channel_ranking_message(service, tournament, value)
        result = send_admin_message(message, chat_id=delivery.recipient_id)
    except Exception as error:
        logger.exception("tournament_daily_delivery_failed delivery_id=%s", delivery_id)
        delivery = db.get(TournamentDailyDelivery, delivery_id)
        if delivery and delivery.status == "SENDING" and delivery.attempts == attempt:
            delivery.status = "FAILED"
            delivery.last_error = type(error).__name__
            if isinstance(error, TelegramNotificationPermanentError):
                delivery.attempts = config.TOURNAMENT_DELIVERY_MAX_ATTEMPTS
            db.commit()
        return False
    delivery = db.get(TournamentDailyDelivery, delivery_id)
    if delivery and delivery.status == "SENDING" and delivery.attempts == attempt:
        delivery.status = "SUCCESS"
        delivery.sent_at = value
        delivery.message_id = str(result.message_id)
        db.commit()
    return True


def run_tournament_worker_tick(db, now: datetime | None = None) -> int:
    value = as_utc(now or utc_now())
    TournamentService(db).finish_due(value)
    local = value.astimezone(ZoneInfo(config.TOURNAMENT_TIMEZONE))
    if local.hour >= config.TOURNAMENT_DAILY_NOTIFICATION_HOUR:
        queue_daily_rankings(db, now=value, delivery_date=local.date())
    processed = 0
    for _ in range(config.TOURNAMENT_DELIVERY_BATCH_SIZE):
        result = process_next_daily_delivery(db, value)
        if result is None:
            break
        processed += 1
    return processed


class TournamentWorker:
    def __init__(self, session_factory, interval_seconds: float | None = None):
        self.session_factory = session_factory
        self.interval_seconds = (
            interval_seconds or config.TOURNAMENT_WORKER_INTERVAL_SECONDS
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tournament-worker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=min(self.interval_seconds + 1, 5))

    def _run(self) -> None:
        while not self._stop.is_set():
            db = self.session_factory()
            try:
                run_tournament_worker_tick(db)
            except Exception:
                db.rollback()
                logger.exception("tournament_worker_tick_failed")
            finally:
                db.close()
            self._stop.wait(self.interval_seconds)
