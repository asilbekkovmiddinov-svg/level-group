from typing import Optional

from pydantic import BaseModel


class OrderCreate(BaseModel):
    telegram_id: int
    product_id: int
    region: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    status: str


class OrderReject(BaseModel):
    admin_id: int
    reason: Optional[str] = "Sabab ko'rsatilmagan"


class OrderAdminAction(BaseModel):
    admin_id: int


class OrderResponse(BaseModel):
    id: int
    telegram_id: int
    product_id: int
    product_title: str
    coins_amount: int
    price_uzs: float
    status: str
    region: Optional[str] = None

    class Config:
        from_attributes = True
