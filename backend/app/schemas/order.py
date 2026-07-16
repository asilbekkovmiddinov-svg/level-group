from typing import Optional

from pydantic import BaseModel


class OrderCreate(BaseModel):
    product_id: int
    region: Optional[str] = None
    # Legacy clients may still send this field. Authentication is authoritative.
    telegram_id: Optional[int] = None
    konami_login: str
    konami_password: str
    platform: str


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
