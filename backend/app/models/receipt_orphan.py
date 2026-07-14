from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func
from app.core.database import Base

class ReceiptOrphan(Base):
    __tablename__ = "receipt_orphans"
    id = Column(Integer, primary_key=True)
    object_key = Column(String(500), nullable=False, unique=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
