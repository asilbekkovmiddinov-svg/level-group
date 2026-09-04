from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.subscription_channel import SubscriptionChannel
from app.schemas.subscription import SubscriptionChannelCreate, SubscriptionChannelUpdate


DEFAULT_REQUIRED_CHANNELS = (
    {"chat_id": "@Bek_PesserUz", "title": "Bek_PesserUz 🇺🇿", "url": "https://t.me/Bek_PesserUz"},
    {"chat_id": "@levelgroup_buyurtmalar", "title": "LEVEL | Completed Orders", "url": "https://t.me/levelgroup_buyurtmalar"},
    {"chat_id": "@ronin_Efootbol", "title": "RONIN eFootball", "url": "https://t.me/ronin_Efootbol"},
)


class SubscriptionChannelError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def seed_subscription_channels(db: Session) -> None:
    if db.query(SubscriptionChannel.id).first() is not None:
        return
    for index, channel in enumerate(DEFAULT_REQUIRED_CHANNELS):
        db.add(SubscriptionChannel(**channel, sort_order=index))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def list_subscription_channels(db: Session) -> list[SubscriptionChannel]:
    return db.query(SubscriptionChannel).order_by(
        SubscriptionChannel.sort_order, SubscriptionChannel.id
    ).all()


def create_subscription_channel(db: Session, payload: SubscriptionChannelCreate) -> SubscriptionChannel:
    if db.query(SubscriptionChannel.id).filter_by(chat_id=payload.chat_id).first():
        raise SubscriptionChannelError(409, "Bu kanal allaqachon ro‘yxatda")
    channel = SubscriptionChannel(
        chat_id=payload.chat_id, title=payload.title, url=payload.url,
        sort_order=payload.sort_order, created_by=payload.admin_id,
        updated_by=payload.admin_id,
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel


def update_subscription_channel(
    db: Session, channel_id: int, payload: SubscriptionChannelUpdate
) -> SubscriptionChannel:
    channel = db.get(SubscriptionChannel, channel_id)
    if channel is None:
        raise SubscriptionChannelError(404, "Kanal topilmadi")
    duplicate = db.query(SubscriptionChannel.id).filter(
        SubscriptionChannel.chat_id == payload.chat_id,
        SubscriptionChannel.id != channel_id,
    ).first()
    if duplicate:
        raise SubscriptionChannelError(409, "Bu kanal allaqachon ro‘yxatda")
    channel.chat_id = payload.chat_id
    channel.title = payload.title
    channel.url = payload.url
    channel.sort_order = payload.sort_order
    channel.updated_by = payload.admin_id
    db.commit()
    db.refresh(channel)
    return channel


def delete_subscription_channel(db: Session, channel_id: int) -> None:
    channel = db.get(SubscriptionChannel, channel_id)
    if channel is None:
        raise SubscriptionChannelError(404, "Kanal topilmadi")
    if db.query(SubscriptionChannel.id).count() <= 1:
        raise SubscriptionChannelError(409, "Majburiy obuna uchun kamida bitta kanal qolishi kerak")
    db.delete(channel)
    db.commit()
