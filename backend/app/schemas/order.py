from pydantic import BaseModel
from typing import Optional


class OrderCreate(BaseModel):
    telegram_id: int
    product_id: int


class OrderStatusUpdate(BaseModel):
    status: str


class OrderReject(BaseModel):
    admin_id: int
    reason: Optional[str] = "Sabab ko‘rsatilmagan"


class OrderAdminAction(BaseModel):
    admin_id: int
