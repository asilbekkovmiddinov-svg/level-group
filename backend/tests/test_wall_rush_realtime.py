from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.websockets import WebSocketDisconnect

from app.core.database import Base
from app.core.telegram_auth import TelegramUser
from app.models.user import User
from app.models.wall_rush import (
    GameTicketLedger, GameTicketWallet, WallRushAction, WallRushMatch,
)
from app.routers import wall_rush as wall_rush_router
from app.services.wall_rush import join_match
from app.models.wall_rush import WallRushMode


def build(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[
        User.__table__, WallRushMatch.__table__, WallRushAction.__table__,
        GameTicketWallet.__table__, GameTicketLedger.__table__,
    ])
    sessions = sessionmaker(bind=engine)
    db = sessions()
    db.add_all([
        User(telegram_id=101, first_name="Red"),
        User(telegram_id=202, first_name="Blue"),
    ])
    db.commit()
    join_match(db, 101, WallRushMode.FREE)
    join_match(db, 202, WallRushMode.FREE)
    db.close()

    monkeypatch.setattr(
        wall_rush_router,
        "verify_init_data",
        lambda _: TelegramUser(101, "Red", None, "uz"),
    )
    monkeypatch.setattr(wall_rush_router, "SessionLocal", sessions)
    app = FastAPI()
    app.include_router(wall_rush_router.router)
    return TestClient(app), engine


def test_websocket_requires_telegram_auth(monkeypatch):
    client, engine = build(monkeypatch)
    try:
        with client.websocket_connect("/wall-rush/ws") as socket:
            socket.receive_json()
    except WebSocketDisconnect as error:
        assert error.code == 4401
    finally:
        engine.dispose()


def test_websocket_sends_resumable_authoritative_match_state(monkeypatch):
    client, engine = build(monkeypatch)
    try:
        with client.websocket_connect("/wall-rush/ws?init_data=verified") as socket:
            message = socket.receive_json()
            assert message["type"] == "MATCH_STATE"
            assert message["match"]["status"] == "ACTIVE"
            assert message["match"]["red_player_id"] == 101
            socket.send_text("PING")
            assert socket.receive_json() == {"type": "PONG"}
    finally:
        engine.dispose()
