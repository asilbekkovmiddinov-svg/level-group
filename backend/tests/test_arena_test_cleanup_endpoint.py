from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.core.database import Base, get_db
from app.models.match import Match, MatchGameType, MatchStatus
from app.models.transaction import Transaction
from app.models.user import User
from app.models.wallet import Wallet
from app.routers import match as match_router


TARGET_ID = 1678146043


def _match(creator, status, opponent=None):
    return Match(
        creator_telegram_id=creator,
        opponent_telegram_id=opponent,
        efc_amount=Decimal("100"),
        total_pool=Decimal("200"),
        commission_amount=Decimal("10"),
        winner_reward=Decimal("190"),
        game_type=MatchGameType.EFOOTBALL,
        status=status,
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_internal_endpoint_cleans_only_authorized_test_matches(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[User.__table__, Wallet.__table__, Transaction.__table__, Match.__table__],
    )
    db = sessionmaker(bind=engine)()
    for telegram_id in (TARGET_ID, 2002, 3003):
        db.add(User(telegram_id=telegram_id, first_name="Arena cleanup test"))
    db.add(Wallet(telegram_id=TARGET_ID, efc_balance=100, locked_efc=200))
    db.add(Wallet(telegram_id=2002, efc_balance=100, locked_efc=100))
    db.add(Wallet(telegram_id=3003, efc_balance=100, locked_efc=100))
    first = _match(TARGET_ID, MatchStatus.WAITING_PLAYER)
    playing = _match(TARGET_ID, MatchStatus.PLAYING, opponent=2002)
    unrelated = _match(3003, MatchStatus.WAITING_PLAYER)
    db.add_all([first, playing, unrelated])
    db.commit()
    match_ids = (first.id, playing.id, unrelated.id)

    monkeypatch.setattr(config, "INTERNAL_API_KEY", "cleanup-test-key")
    app = FastAPI()
    app.include_router(match_router.router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    assert client.post("/matches/internal/test-cleanup").status_code == 401
    response = client.post(
        "/matches/internal/test-cleanup",
        headers={"X-Internal-Api-Key": "cleanup-test-key"},
        json={"telegram_id": TARGET_ID},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["telegram_id"] == TARGET_ID
    assert payload["cleaned_count"] == 2
    assert payload["locked_efc_zero"] is True
    assert payload["new_match_allowed"] is True
    assert {item["match_id"] for item in payload["transitions"]} == set(match_ids[:2])

    db.expire_all()
    assert db.query(Match).filter(Match.id.in_(match_ids[:2])).filter(
        Match.status == MatchStatus.CANCELLED
    ).count() == 2
    assert db.query(Match).filter(Match.id == match_ids[2]).one().status == MatchStatus.WAITING_PLAYER
    assert db.query(Wallet).filter(Wallet.telegram_id == TARGET_ID).one().locked_efc == 0
    assert db.query(Wallet).filter(Wallet.telegram_id == 2002).one().locked_efc == 0
    assert db.query(Wallet).filter(Wallet.telegram_id == 3003).one().locked_efc == 100
    assert db.query(Transaction).filter(Transaction.type == "MATCH_UNLOCK").count() == 3
    db.close()


def test_cleanup_openapi_exposes_required_confirming_body():
    app = FastAPI()
    app.include_router(match_router.router)

    operation = app.openapi()["paths"]["/matches/internal/test-cleanup"]["post"]
    body = operation["requestBody"]
    schema = body["content"]["application/json"]["schema"]

    assert body["required"] is True
    assert schema["$ref"].endswith("/ArenaTestCleanupRequest")
    request_schema = app.openapi()["components"]["schemas"]["ArenaTestCleanupRequest"]
    assert request_schema["required"] == ["telegram_id"]
    assert request_schema["properties"]["telegram_id"]["const"] == TARGET_ID
