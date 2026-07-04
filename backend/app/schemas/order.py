from pydantic import BaseModel


class OrderCreate(BaseModel):
    telegram_id: int
    product_id: int


class OrderStatusUpdate(BaseModel):
    status: str
