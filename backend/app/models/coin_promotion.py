from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.sql import func

from app.core.database import Base


COIN_PROMOTION_STATUSES = ("DRAFT", "ACTIVE", "PAUSED", "EXPIRED", "DELETED")


class CoinPromotion(Base):
    __tablename__ = "coin_promotions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT','ACTIVE','PAUSED','EXPIRED','DELETED')",
            name="ck_coin_promotions_status",
        ),
        CheckConstraint("original_price > 0", name="ck_coin_promotions_original_price"),
        CheckConstraint("promotion_price > 0 AND promotion_price < original_price", name="ck_coin_promotions_price"),
        CheckConstraint("total_quantity > 0", name="ck_coin_promotions_total_quantity"),
        CheckConstraint("reserved_quantity >= 0", name="ck_coin_promotions_reserved_quantity"),
        CheckConstraint("sold_quantity >= 0", name="ck_coin_promotions_sold_quantity"),
        CheckConstraint(
            "reserved_quantity + sold_quantity <= total_quantity",
            name="ck_coin_promotions_inventory",
        ),
        CheckConstraint("per_user_limit > 0", name="ck_coin_promotions_per_user_limit"),
        CheckConstraint("end_at > start_at", name="ck_coin_promotions_schedule"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(160), nullable=False)
    status = Column(String(20), nullable=False, default="DRAFT", index=True)
    coin_package_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    original_price = Column(Numeric(18, 2), nullable=False)
    promotion_price = Column(Numeric(18, 2), nullable=False)
    total_quantity = Column(Integer, nullable=False)
    reserved_quantity = Column(Integer, nullable=False, default=0)
    sold_quantity = Column(Integer, nullable=False, default=0)
    start_at = Column(DateTime(timezone=True), nullable=False, index=True)
    end_at = Column(DateTime(timezone=True), nullable=False, index=True)
    per_user_limit = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.total_quantity - self.reserved_quantity - self.sold_quantity)
