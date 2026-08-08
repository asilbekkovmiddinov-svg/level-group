from enum import Enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CoinPackageScope(str, Enum):
    ALL = "ALL"
    ANDROID = "ANDROID"
    JAPAN = "JAPAN"
    TURKEY = "TURKEY"


class CoinPackageCreate(BaseModel):
    coin_amount: int = Field(gt=0)
    price_uzs: float = Field(gt=0)
    scope: CoinPackageScope
    is_active: bool = True


class CoinPackageUpdate(CoinPackageCreate):
    pass


class CoinPackageAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    platform: str | None
    region: str | None
    scope: CoinPackageScope
    coin_amount: int
    price_uzs: float
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
