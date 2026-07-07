from typing import Optional

from pydantic import BaseModel


class ProductCreate(BaseModel):
    title: str
    category: str
    platform: Optional[str] = None
    region: Optional[str] = None
    coins_amount: int
    price_uzs: float
    description: Optional[str] = None
    order_index: Optional[int] = 0


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    platform: Optional[str] = None
    region: Optional[str] = None
    coins_amount: Optional[int] = None
    price_uzs: Optional[float] = None
    description: Optional[str] = None
    order_index: Optional[int] = None
    is_active: Optional[bool] = None


class ProductResponse(BaseModel):
    id: int
    title: str
    category: str
    platform: Optional[str]
    region: Optional[str]
    coins_amount: int
    price_uzs: float
    description: Optional[str]
    order_index: int
    is_active: bool

    class Config:
        from_attributes = True
