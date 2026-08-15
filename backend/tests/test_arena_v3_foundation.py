from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models
from app.core import config
from app.core.arena_v3_migrations import run_arena_v3_migrations
from app.core.database import Base, get_db
from app.core.telegram_auth import get_current_telegram_user
from app.models.arena_v3 import (
    ArenaV3Match, ArenaV3Status, ArenaV3SettlementStatus,
)
from app.models.wall_rush import GameTicketWallet
from app.repositories.arena_v3 import ArenaV3Repository
from app.routers.arena_v3 import router
from app.schemas.arena_v3 import ArenaV3CreateRequest, ArenaV3RoomCodeRequest
from app.services.arena_v3_state_machine import (
    ArenaV3InvalidTransition, ensure_arena_v3_transition, transition_arena_v3,
)


@pytest.fixture
def engine():
    value = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(value)
    return value


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def make_match(**overrides):
    values = {
        "public_id": "ARV3TEST0001",
        "owner_id": 1001,
        "owner_efootball_username": "Owner",
        "stake_efc": Decimal("100"),
        "total_pool_efc": Decimal("200"),
        "commission_efc": Decimal("10"),
        "winner_reward_efc": Decimal("190"),
        "ticket_cost": 2,
        "match_type": "STANDARD",
        "match_time_minutes": 10,
        "extra_time_enabled": False,
        "penalties_enabled": True,
        "status": ArenaV3Status.OPEN,
        "settlement_status": ArenaV3SettlementStatus.NOT_STARTED,
        "idempotency_key": "create-1",
        "request_fingerprint": "a" * 64,
    }
    values.update(overrides)
    return ArenaV3Match(**values)


def test_migration_creates_only_seven_v3_tables(engine):
    run_arena_v3_migrations(engine)
    names = set(inspect(engine).get_table_names())
    expected = {
        "arena_matches",
        "arena_match_screenshots",
        "arena_ai_reviews",
        "arena_appeals",
        "arena_match_events",
        "arena_notification_deliveries_v3",
        "arena_stats_v3",
    }
    assert expected <= names
    run_arena_v3_migrations(engine)


def test_model_constraints_and_indexes_are_declared():
    match_constraints = {item.name for item in ArenaV3Match.__table__.constraints}
    assert "uq_arena_matches_public_id" in match_constraints
    assert "uq_arena_matches_owner_idempotency" in match_constraints
    assert "ck_arena_matches_time" in match_constraints
    assert "ck_arena_matches_penalties_required" in match_constraints
    indexes = {item.name for item in ArenaV3Match.__table__.indexes}
    assert "ix_arena_matches_status_created" in indexes
    assert "ix_arena_matches_status_stake" in indexes


def test_validation_rejects_identity_injection_and_invalid_rules():
    valid = {
        "owner_efootball_username": " Player ",
        "stake_efc": "100",
        "match_type": "STANDARD",
        "match_time_minutes": 10,
        "extra_time_enabled": False,
        "penalties_enabled": True,
        "rules_accepted": True,
    }
    parsed = ArenaV3CreateRequest.model_validate(valid)
    assert parsed.owner_efootball_username == "Player"

    with pytest.raises(ValidationError):
        ArenaV3CreateRequest.model_validate({**valid, "owner_id": 9999})
    with pytest.raises(ValidationError):
        ArenaV3CreateRequest.model_validate({**valid, "match_time_minutes": 16})
    with pytest.raises(ValidationError):
        ArenaV3CreateRequest.model_validate({**valid, "penalties_enabled": False})
    with pytest.raises(ValidationError):
        ArenaV3RoomCodeRequest.model_validate({"room_code": "123456789"})


def test_state_machine_allows_only_frozen_lifecycle():
    expected = [
        ArenaV3Status.OPEN,
        ArenaV3Status.READY,
        ArenaV3Status.WAITING_ROOM_CODE,
        ArenaV3Status.PLAYING,
        ArenaV3Status.WAITING_SCREENSHOT,
        ArenaV3Status.AI_REVIEW,
        ArenaV3Status.FINISHED,
    ]
    for current, target in zip(expected, expected[1:]):
        ensure_arena_v3_transition(current, target)

    with pytest.raises(ArenaV3InvalidTransition):
        ensure_arena_v3_transition(ArenaV3Status.OPEN, ArenaV3Status.PLAYING)
    with pytest.raises(ArenaV3InvalidTransition):
        ensure_arena_v3_transition(ArenaV3Status.FINISHED, ArenaV3Status.OPEN)

    match = SimpleNamespace(status=ArenaV3Status.OPEN, version=1)
    transition_arena_v3(match, ArenaV3Status.CANCELLED)
    assert match.status == ArenaV3Status.CANCELLED
    assert match.version == 2


def test_repository_flush_get_lock_and_open_listing(db):
    repository = ArenaV3Repository(db)
    match = repository.add_match(make_match())
    assert match.id is not None
    assert repository.get_match(match.id) is match
    assert repository.get_match_for_update(match.id).id == match.id
    assert repository.get_by_owner_idempotency(1001, "create-1").id == match.id
    assert [item.id for item in repository.list_open()] == [match.id]


@pytest.fixture
def client(engine, monkeypatch):
    session_factory = sessionmaker(bind=engine)
    seed = session_factory()
    seed.add(GameTicketWallet(
        telegram_id=1001,
        tournament_tickets=20,
        locked_tournament_tickets=0,
    ))
    seed.commit()
    seed.close()
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_current_telegram_user] = lambda: SimpleNamespace(
        telegram_id=1001
    )

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(config, "ARENA_V3_ALLOWED_TELEGRAM_IDS", frozenset())
    return TestClient(application)


def test_api_requires_feature_access(client, monkeypatch):
    monkeypatch.setattr(config, "ARENA_V3_ENABLED", False)
    response = client.get("/arena/config")
    assert response.status_code == 404


def test_api_safe_flags_validation_and_foundation_boundary(client, monkeypatch):
    monkeypatch.setattr(config, "ARENA_V3_ENABLED", True)
    monkeypatch.setattr(config, "ARENA_V3_CREATE_ENABLED", False)
    monkeypatch.setattr(config, "ARENA_V3_AI_ENABLED", False)
    monkeypatch.setattr(config, "ARENA_V3_SETTLEMENT_ENABLED", False)

    config_response = client.get("/arena/config")
    assert config_response.status_code == 200
    assert config_response.json()["match_time_minutes"] == list(range(6, 16))
    assert config_response.json()["penalties_required"] is True

    payload = {
        "owner_efootball_username": "Player",
        "stake_efc": 0,
        "match_type": "STANDARD",
        "match_time_minutes": 10,
        "extra_time_enabled": False,
        "penalties_enabled": True,
        "rules_accepted": True,
    }
    assert client.post("/arena/create", json=payload).status_code == 400
    headers = {"Idempotency-Key": "create-test"}
    assert client.post("/arena/create", json=payload, headers=headers).status_code == 503

    monkeypatch.setattr(config, "ARENA_V3_CREATE_ENABLED", True)
    response = client.post("/arena/create", json=payload, headers=headers)
    assert response.status_code == 201
    assert response.json()["status"] == "OPEN"


def test_v2_routes_are_not_modified_by_v3_router():
    paths = {route.path for route in router.routes}
    assert all(not path.startswith("/matches") for path in paths)
