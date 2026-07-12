from sqlalchemy import Column, BigInteger, String, Boolean, DateTime
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True, index=True)

    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=True)
    language = Column(String(10), default="uz")

    is_banned = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    last_login = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    last_seen_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
