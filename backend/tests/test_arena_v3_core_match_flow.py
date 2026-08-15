from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core import config
from app.core.database import Base, get_db
from app.core.telegram_auth import get_current_telegram_user
from app.models.arena_v3 import ArenaV3Match, ArenaV3MatchEvent, ArenaV3Status
from app.models.wall_rush import GameTicketWallet
from app.routers.arena_v3 import router as arena_v3_router
from app.schemas.arena_v3 import (
    ArenaV3CancelRequest,
    ArenaV3CreateRequest,
    ArenaV3JoinRequest,
    ArenaV3ReadyRequest,
    ArenaV3RoomCodeRequest,
)
from app.services.arena_v3 import (
    ArenaV3Conflict,
    ArenaV3Forbidden,
    ArenaV3Service,
    ArenaV3ServiceError,
)


@pytest.fixture
def session_factory(monkeypatch):
    monkeypatch.setattr(config, "ARENA_V3_CREATE_ENABLED", True)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    for player_id in (1001, 2002, 3003, 9999):
        db.add(GameTicketWallet(
            telegram_id=player_id,
            tournament_tickets=20,
            locked_tournament_tickets=0,
        ))
    db.commit()
    db.close()
    return factory


def create_payload(**overrides):
    values = {
        "owner_efootball_username": "Owner",
        "stake_efc": "0.00",
        "match_type": "STANDARD",
        "match_time_minutes": 10,
        "extra_time_enabled": False,
        "penalties_enabled": True,
        "rules_accepted": True,
    }
    values.update(overrides)
    return ArenaV3CreateRequest.model_validate(values)


def join_payload():
    return ArenaV3JoinRequest(
        opponent_efootball_username="Opponent",
        rules_accepted=True,
    )


def create_match(db, owner_id=1001, key="create-1"):
    return ArenaV3Service(db).create_match(
        payload=create_payload(),
        owner_id=owner_id,
        idempotency_key=key,
    )


def test_service_runs_complete_core_flow_and_records_events(session_factory):
    db = session_factory()
    match = create_match(db)
    assert match.status == ArenaV3Status.OPEN
    assert match.stake_efc == Decimal("0.00")
    assert match.total_pool_efc == Decimal("0.00")
    assert match.ticket_cost == 2
    assert match.owner_ticket_state == "LOCKED"
    owner_wallet = db.get(GameTicketWallet, 1001)
    assert owner_wallet.tournament_tickets == 18
    assert owner_wallet.locked_tournament_tickets == 2

    match = ArenaV3Service(db).join_match(
        match_id=match.id,
        payload=join_payload(),
        opponent_id=2002,
        idempotency_key="join-1",
    )
    assert match.status == ArenaV3Status.READY
    assert match.opponent_id == 2002
    assert match.owner_efootball_username == "Owner"
    assert match.opponent_efootball_username == "Opponent"
    assert match.opponent_ticket_state == "LOCKED"

    match = ArenaV3Service(db).ready(
        match_id=match.id,
        player_id=1001,
        payload=ArenaV3ReadyRequest(),
    )
    assert match.status == ArenaV3Status.READY
    assert match.owner_ready_at is not None

    match = ArenaV3Service(db).ready(
        match_id=match.id,
        player_id=2002,
        payload=ArenaV3ReadyRequest(),
    )
    assert match.status == ArenaV3Status.WAITING_ROOM_CODE

    match = ArenaV3Service(db).submit_room_code(
        match_id=match.id,
        owner_id=1001,
        payload=ArenaV3RoomCodeRequest(room_code=" 123456 "),
    )
    assert match.status == ArenaV3Status.PLAYING
    assert match.owner_ticket_state == "SPENT"
    assert match.opponent_ticket_state == "SPENT"
    assert db.get(GameTicketWallet, 1001).locked_tournament_tickets == 0
    assert db.get(GameTicketWallet, 2002).locked_tournament_tickets == 0
    assert match.room_code == "123456"
    assert match.playing_started_at is not None
    assert match.screenshot_started_at is not None
    assert (
        match.screenshot_started_at - match.playing_started_at
    ).total_seconds() == match.match_time_minutes * 60
    assert (
        match.screenshot_deadline_at - match.screenshot_started_at
        ).total_seconds() == 600
    assert db.query(ArenaV3MatchEvent).filter_by(match_id=match.id).count() == 5


@pytest.mark.parametrize("match_time_minutes", [6, 8, 10, 12, 15])
def test_room_code_schedules_screenshot_window_after_match_time(
    session_factory, match_time_minutes
):
    db = session_factory()
    service = ArenaV3Service(db)
    match = service.create_match(
        payload=create_payload(match_time_minutes=match_time_minutes),
        owner_id=1001,
        idempotency_key=f"duration-{match_time_minutes}",
    )
    match = service.join_match(
        match_id=match.id,
        opponent_id=2002,
        payload=join_payload(),
        idempotency_key=f"join-{match_time_minutes}",
    )
    service.ready(
        match_id=match.id, player_id=1001, payload=ArenaV3ReadyRequest()
    )
    service.ready(
        match_id=match.id, player_id=2002, payload=ArenaV3ReadyRequest()
    )

    match = service.submit_room_code(
        match_id=match.id,
        owner_id=1001,
        payload=ArenaV3RoomCodeRequest(room_code="ROOM"),
    )

    assert match.status == ArenaV3Status.PLAYING
    assert (
        match.screenshot_started_at - match.playing_started_at
    ).total_seconds() == match_time_minutes * 60
    assert (
        match.screenshot_deadline_at - match.screenshot_started_at
        ).total_seconds() == 600


def test_create_and_join_are_idempotent_and_protect_active_players(session_factory):
    db = session_factory()
    service = ArenaV3Service(db)
    first = service.create_match(
        payload=create_payload(), owner_id=1001, idempotency_key="same"
    )
    repeated = service.create_match(
        payload=create_payload(), owner_id=1001, idempotency_key="same"
    )
    assert repeated.id == first.id

    with pytest.raises(ArenaV3Conflict, match="payload mismatch"):
        service.create_match(
            payload=create_payload(owner_efootball_username="Changed"),
            owner_id=1001,
            idempotency_key="same",
        )
    with pytest.raises(ArenaV3Conflict, match="active"):
        service.create_match(
            payload=create_payload(), owner_id=1001, idempotency_key="other"
        )
    with pytest.raises(ArenaV3Conflict, match="own match"):
        service.join_match(
            match_id=first.id,
            payload=join_payload(),
            opponent_id=1001,
            idempotency_key="self",
        )


def test_two_tickets_are_required_for_create_and_join(session_factory):
    db = session_factory()
    db.get(GameTicketWallet, 3003).tournament_tickets = 1
    db.commit()
    with pytest.raises(ArenaV3Conflict, match="kamida 2"):
        ArenaV3Service(db).create_match(
            payload=create_payload(), owner_id=3003, idempotency_key="poor-owner"
        )

    match = create_match(db)
    db.get(GameTicketWallet, 2002).tournament_tickets = 1
    db.commit()
    with pytest.raises(ArenaV3Conflict, match="kamida 2"):
        ArenaV3Service(db).join_match(
            match_id=match.id,
            payload=join_payload(),
            opponent_id=2002,
            idempotency_key="poor-opponent",
        )
    db.refresh(match)
    assert match.status == ArenaV3Status.OPEN
    assert match.opponent_id is None


def test_permissions_invalid_states_and_match_type_validation(session_factory):
    db = session_factory()
    match = create_match(db)
    with pytest.raises(ArenaV3ServiceError, match="Unsupported"):
        ArenaV3Service(db).create_match(
            payload=create_payload(match_type="CUSTOM"),
            owner_id=3003,
            idempotency_key="unsupported",
        )
    with pytest.raises(ArenaV3Forbidden):
        ArenaV3Service(db).ready(
            match_id=match.id, player_id=9999, payload=ArenaV3ReadyRequest()
        )

    joined = ArenaV3Service(db).join_match(
        match_id=match.id,
        payload=join_payload(),
        opponent_id=2002,
        idempotency_key="join",
    )
    with pytest.raises(ArenaV3Forbidden):
        ArenaV3Service(db).submit_room_code(
            match_id=joined.id,
            owner_id=2002,
            payload=ArenaV3RoomCodeRequest(room_code="123"),
        )
    with pytest.raises(ArenaV3Conflict):
        ArenaV3Service(db).submit_room_code(
            match_id=joined.id,
            owner_id=1001,
            payload=ArenaV3RoomCodeRequest(room_code="123"),
        )


@pytest.mark.parametrize(
    "stage",
    ["OPEN", "READY", "WAITING_ROOM_CODE"],
)
def test_cancel_is_allowed_only_before_playing(session_factory, stage):
    db = session_factory()
    match = create_match(db)
    service = ArenaV3Service(db)
    if stage != "OPEN":
        match = service.join_match(
            match_id=match.id,
            payload=join_payload(),
            opponent_id=2002,
            idempotency_key="join",
        )
    if stage == "WAITING_ROOM_CODE":
        service.ready(match_id=match.id, player_id=1001, payload=ArenaV3ReadyRequest())
        match = service.ready(
            match_id=match.id, player_id=2002, payload=ArenaV3ReadyRequest()
        )
    cancelled = service.cancel_match(
        match_id=match.id,
        player_id=match.owner_id,
        payload=ArenaV3CancelRequest(reason_code="USER_CANCELLED"),
        idempotency_key=f"cancel-{stage}",
    )
    assert cancelled.status == ArenaV3Status.CANCELLED
    assert cancelled.owner_ticket_state == "REFUNDED"
    assert db.get(GameTicketWallet, 1001).tournament_tickets == 20
    if stage != "OPEN":
        assert cancelled.opponent_ticket_state == "REFUNDED"
        assert db.get(GameTicketWallet, 2002).tournament_tickets == 20


def test_playing_match_cannot_be_cancelled(session_factory):
    db = session_factory()
    service = ArenaV3Service(db)
    match = create_match(db)
    service.join_match(
        match_id=match.id, payload=join_payload(),
        opponent_id=2002, idempotency_key="join",
    )
    service.ready(match_id=match.id, player_id=1001, payload=ArenaV3ReadyRequest())
    service.ready(match_id=match.id, player_id=2002, payload=ArenaV3ReadyRequest())
    service.submit_room_code(
        match_id=match.id, owner_id=1001,
        payload=ArenaV3RoomCodeRequest(room_code="123"),
    )
    with pytest.raises(ArenaV3Conflict, match="cannot be cancelled"):
        service.cancel_match(
            match_id=match.id,
            player_id=1001,
            payload=ArenaV3CancelRequest(reason_code="TOO_LATE"),
            idempotency_key="late",
        )


@pytest.fixture
def api(session_factory, monkeypatch):
    actor = {"telegram_id": 1001}
    application = FastAPI()
    application.include_router(arena_v3_router)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_current_telegram_user] = lambda: SimpleNamespace(
        telegram_id=actor["telegram_id"]
    )
    monkeypatch.setattr(config, "ARENA_V3_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_CREATE_ENABLED", True)
    return TestClient(application), actor


def test_api_endpoints_complete_core_flow(api):
    client, actor = api
    create_response = client.post(
        "/arena/create",
        json=create_payload().model_dump(mode="json"),
        headers={"Idempotency-Key": "api-create"},
    )
    assert create_response.status_code == 201
    match_id = create_response.json()["id"]
    assert client.get("/arena/open").json()["matches"][0]["id"] == match_id
    assert client.get("/arena/active").json()["match"]["id"] == match_id
    assert client.get(f"/arena/{match_id}").status_code == 200

    actor["telegram_id"] = 2002
    join_response = client.post(
        f"/arena/{match_id}/join",
        json=join_payload().model_dump(mode="json"),
        headers={"Idempotency-Key": "api-join"},
    )
    assert join_response.status_code == 200
    assert join_response.json()["status"] == "READY"
    assert client.post(f"/arena/{match_id}/ready", json={}).status_code == 200

    actor["telegram_id"] = 1001
    ready_response = client.post(f"/arena/{match_id}/ready", json={})
    assert ready_response.json()["status"] == "WAITING_ROOM_CODE"
    room_response = client.post(
        f"/arena/{match_id}/room-code", json={"room_code": "ABC123"}
    )
    assert room_response.status_code == 200
    assert room_response.json()["status"] == "PLAYING"


@pytest.mark.parametrize(
    ("status", "is_active", "in_history"),
    [
        (ArenaV3Status.CANCELLED, False, True),
        (ArenaV3Status.FINISHED, False, True),
        (ArenaV3Status.AI_REVIEW, False, False),
        (ArenaV3Status.PLAYING, True, False),
    ],
)
def test_active_endpoint_excludes_terminal_matches_and_history_keeps_them(
    api, session_factory, status, is_active, in_history
):
    client, actor = api
    actor["telegram_id"] = 1001
    created = client.post(
        "/arena/create",
        json=create_payload().model_dump(mode="json"),
        headers={"Idempotency-Key": f"terminal-active-{status.value}"},
    ).json()
    db = session_factory()
    stored = db.get(ArenaV3Match, created["id"])
    stored.status = status
    db.commit()
    db.close()

    active = client.get("/arena/active").json()["match"]
    assert (active is not None) is is_active
    history_ids = {
        item["id"] for item in client.get("/arena/history").json()["matches"]
    }
    assert (created["id"] in history_ids) is in_history

    if not is_active:
        replacement = client.post(
            "/arena/create",
            json=create_payload().model_dump(mode="json"),
            headers={"Idempotency-Key": f"replacement-{status.value}"},
        )
        assert replacement.status_code == 201


def test_api_validation_permissions_flags_and_v2_route_regression(api, monkeypatch):
    client, actor = api
    invalid = create_payload().model_dump(mode="json")
    invalid["match_time_minutes"] = 16
    assert client.post(
        "/arena/create", json=invalid, headers={"Idempotency-Key": "invalid"}
    ).status_code == 422

    monkeypatch.setattr(config, "ARENA_V3_CREATE_ENABLED", False)
    assert client.post(
        "/arena/create",
        json=create_payload().model_dump(mode="json"),
        headers={"Idempotency-Key": "disabled"},
    ).status_code == 503
    monkeypatch.setattr(config, "ARENA_V3_CREATE_ENABLED", True)

    created = client.post(
        "/arena/create",
        json=create_payload().model_dump(mode="json"),
        headers={"Idempotency-Key": "permissions"},
    ).json()
    actor["telegram_id"] = 9999
    assert client.post(f"/arena/{created['id']}/ready", json={}).status_code == 403

    actor["telegram_id"] = 2002
    client.post(
        f"/arena/{created['id']}/join",
        json=join_payload().model_dump(mode="json"),
        headers={"Idempotency-Key": "detail-join"},
    )
    actor["telegram_id"] = 9999
    assert client.get(f"/arena/{created['id']}").status_code == 403

    paths = {route.path for route in arena_v3_router.routes}
    assert all(not path.startswith("/matches") for path in paths)
