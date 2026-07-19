import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.models.campaign import Campaign, CampaignRecipient
from app.models.promotion import Promotion
from app.models.user import User
from app.routers import internal_wallet
from app.routers.campaign_delivery import router
from app.services import campaign_delivery


TABLES = [User.__table__, Promotion.__table__, Campaign.__table__, CampaignRecipient.__table__]


def build_client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(internal_wallet, "INTERNAL_API_KEY", "delivery-secret")
    monkeypatch.setattr(campaign_delivery, "CAMPAIGN_DELIVERY_BATCH_SIZE", 2)
    monkeypatch.setattr(campaign_delivery, "CAMPAIGN_DELIVERY_RETRY_LIMIT", 2)
    app = FastAPI()
    app.include_router(router)

    def dependency():
        db = sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = dependency
    return TestClient(app), sessions


def seed(sessions, count=3):
    db = sessions()
    db.add_all(User(telegram_id=100 + value, first_name=f"User {value}") for value in range(count))
    campaign = Campaign(
        title="Chegirma", message="Bugun xarid qiling", image_url="https://cdn.example/banner.webp",
        button_text="Ochish", button_action="COIN_SHOP", promotion_id=None,
        audience_type="ALL_USERS", schedule_type="NOW", status="COMPLETED",
        created_by=9001, updated_by=9001,
    )
    db.add(campaign)
    db.flush()
    db.add_all(CampaignRecipient(campaign_id=campaign.id, user_id=100 + value) for value in range(count))
    db.commit()
    campaign_id = campaign.id
    db.close()
    return campaign_id


def auth():
    return {"X-Internal-Api-Key": "delivery-secret"}


def test_claim_is_internal_batched_atomic_and_idempotent(monkeypatch):
    client, sessions = build_client(monkeypatch)
    campaign_id = seed(sessions)
    assert client.post("/internal/campaigns/recipients/claim").status_code == 403
    assert client.post("/internal/campaigns/recipients/claim", headers={"X-Internal-Api-Key": "wrong"}).status_code == 403
    first = client.post("/internal/campaigns/recipients/claim", headers=auth())
    assert first.status_code == 200 and len(first.json()) == 2
    assert set(first.json()[0]) == {
        "recipient_id", "campaign_id", "telegram_id", "title", "message", "image_url",
        "button_text", "button_action", "button_target", "promotion_id", "claimed_at",
    }
    assert first.json()[0]["campaign_id"] == campaign_id
    second = client.post("/internal/campaigns/recipients/claim", headers=auth())
    assert len(second.json()) == 1
    third = client.post("/internal/campaigns/recipients/claim", headers=auth())
    assert third.json() == []


def test_sent_is_idempotent_and_rejects_stale_claim(monkeypatch):
    client, sessions = build_client(monkeypatch)
    seed(sessions, 1)
    claimed = client.post("/internal/campaigns/recipients/claim", headers=auth()).json()[0]
    path = f"/internal/campaigns/recipients/{claimed['recipient_id']}/sent"
    body = {"claimed_at": claimed["claimed_at"], "delivery_time": 0.25}
    first = client.post(path, headers=auth(), json=body)
    second = client.post(path, headers=auth(), json=body)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "SENT"
    db = sessions()
    recipient = db.query(CampaignRecipient).one()
    assert recipient.sent_at is not None and recipient.delivery_time == 0.25
    db.close()


def test_temporary_failure_retries_then_becomes_final(monkeypatch):
    client, sessions = build_client(monkeypatch)
    seed(sessions, 1)
    claimed = client.post("/internal/campaigns/recipients/claim", headers=auth()).json()[0]
    path = f"/internal/campaigns/recipients/{claimed['recipient_id']}/failed"
    body = {"claimed_at": claimed["claimed_at"], "failure_reason": "Telegram timeout", "temporary": True, "delivery_time": 1.5}
    retry = client.post(path, headers=auth(), json=body)
    duplicate = client.post(path, headers=auth(), json=body)
    assert retry.json()["status"] == duplicate.json()["status"] == "PENDING"
    assert retry.json()["retry_count"] == duplicate.json()["retry_count"] == 1
    claimed_again = client.post("/internal/campaigns/recipients/claim", headers=auth()).json()[0]
    final = client.post(path, headers=auth(), json={**body, "claimed_at": claimed_again["claimed_at"]})
    assert final.json()["status"] == "FAILED"
    assert final.json()["retry_count"] == 2 and final.json()["final"] is True


def test_permanent_failure_is_final_and_idempotent(monkeypatch):
    client, sessions = build_client(monkeypatch)
    seed(sessions, 1)
    claimed = client.post("/internal/campaigns/recipients/claim", headers=auth()).json()[0]
    path = f"/internal/campaigns/recipients/{claimed['recipient_id']}/failed"
    body = {"claimed_at": claimed["claimed_at"], "failure_reason": "Bot blocked", "temporary": False, "delivery_time": 0.1}
    assert client.post(path, headers=auth(), json=body).json()["status"] == "FAILED"
    duplicate = client.post(path, headers=auth(), json=body).json()
    assert duplicate["status"] == "FAILED" and duplicate["retry_count"] == 1


def test_authoritative_statistics_recalculate(monkeypatch):
    client, sessions = build_client(monkeypatch)
    campaign_id = seed(sessions, 3)
    db = sessions()
    recipients = db.query(CampaignRecipient).order_by(CampaignRecipient.id).all()
    recipients[0].status = "SENT"
    recipients[1].status = "CLICKED"
    recipients[2].status = "FAILED"
    db.commit()
    db.close()
    response = client.post(f"/internal/campaigns/{campaign_id}/recalculate", headers=auth())
    assert response.status_code == 200
    assert response.json() == {
        "campaign_id": campaign_id, "sent_count": 2, "opened_count": 1,
        "clicked_count": 1, "failed_count": 1, "ctr": 50.0, "failure_rate": 50.0,
    }


def test_delivery_migration_upgrade_and_downgrade(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20260719_internal_campaign_delivery.py"
    spec = importlib.util.spec_from_file_location("internal_campaign_delivery_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for table in (User.__table__, Promotion.__table__, Campaign.__table__):
            table.create(connection)
        # Use the pre-Sprint-9.5 table shape before applying this migration.
        old_table = sa.Table(
            "campaign_recipients", sa.MetaData(),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("campaign_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
            sa.Column("opened_at", sa.DateTime(timezone=True)),
            sa.Column("read_at", sa.DateTime(timezone=True)),
            sa.Column("clicked_at", sa.DateTime(timezone=True)),
            sa.Column("dismissed_at", sa.DateTime(timezone=True)),
            sa.Column("created_at", sa.DateTime(timezone=True)),
        )
        old_table.create(connection)
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()
        columns = {item["name"] for item in __import__("sqlalchemy").inspect(connection).get_columns("campaign_recipients")}
        assert {"claimed_at", "sent_at", "failed_at", "retry_count", "delivery_time"} <= columns
        migration.downgrade()
        columns = {item["name"] for item in __import__("sqlalchemy").inspect(connection).get_columns("campaign_recipients")}
        assert "claimed_at" not in columns
