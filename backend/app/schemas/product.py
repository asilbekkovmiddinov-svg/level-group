from pydantic import BaseModel
from typing import Optional


class ProductCreate(BaseModel):
    title: str
    category: str
    platform: Optional[str] = None
    region: Optional[str] = None
    coins_amount: int
    price_uzs: float


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    platform: Optional[str] = None
    region: Optional[str] = None
    coins_amount: Optional[int] = None
    price_uzs: Optional[float] = None
    is_active: Optional[bool] = None


class ProductResponse(BaseModel):
    id: int
    title: str
    category: str
    platform: Optional[str]
    region: Optional[str]
    coins_amount: int
    price_uzs: float
    is_active: bool

    class Config:
        from_attributes = True
