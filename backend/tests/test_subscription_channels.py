from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.telegram_auth import TelegramUser
from app.models.subscription_channel import SubscriptionChannel
from app.routers.subscription import subscription_status
from app.schemas.subscription import SubscriptionChannelCreate, SubscriptionChannelUpdate
from app.services.subscription_channels import (
    SubscriptionChannelError,
    create_subscription_channel,
    delete_subscription_channel,
    list_subscription_channels,
    seed_subscription_channels,
    update_subscription_channel,
)


def build():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[SubscriptionChannel.__table__])
    db = sessionmaker(bind=engine)()
    return db, engine


def payload(**overrides):
    values = {
        "chat_id": "@new_channel",
        "title": "New Channel",
        "url": "https://t.me/new_channel",
        "sort_order": 10,
        "admin_id": 9001,
    }
    values.update(overrides)
    return values


def test_admin_can_seed_add_replace_and_delete_channels():
    db, engine = build()
    try:
        seed_subscription_channels(db)
        assert len(list_subscription_channels(db)) == 3

        created = create_subscription_channel(db, SubscriptionChannelCreate(**payload()))
        updated = update_subscription_channel(
            db,
            created.id,
            SubscriptionChannelUpdate(**payload(
                chat_id="@replacement_channel",
                title="Replacement",
                url="https://t.me/replacement_channel",
            )),
        )
        assert updated.chat_id == "@replacement_channel"

        delete_subscription_channel(db, created.id)
        assert all(row.id != created.id for row in list_subscription_channels(db))
    finally:
        db.close()
        engine.dispose()


def test_last_required_channel_cannot_be_deleted():
    db, engine = build()
    try:
        channel = create_subscription_channel(db, SubscriptionChannelCreate(**payload()))
        with pytest.raises(SubscriptionChannelError, match="kamida bitta"):
            delete_subscription_channel(db, channel.id)
    finally:
        db.close()
        engine.dispose()


def test_miniapp_status_uses_current_database_channel_list():
    db, engine = build()
    try:
        first = create_subscription_channel(db, SubscriptionChannelCreate(**payload()))
        create_subscription_channel(db, SubscriptionChannelCreate(**payload(
            chat_id="@second_channel",
            title="Second Channel",
            url="https://t.me/second_channel",
        )))
        user = TelegramUser(telegram_id=101, first_name="One", username="one", language="uz")
        with patch(
            "app.routers.subscription._is_member",
            side_effect=lambda chat_id, _user_id: chat_id != first.chat_id,
        ):
            result = subscription_status(current_user=user, db=db)
        assert result == {
            "subscribed": False,
            "missing_channels": [{"title": "New Channel", "url": "https://t.me/new_channel"}],
        }
    finally:
        db.close()
        engine.dispose()
