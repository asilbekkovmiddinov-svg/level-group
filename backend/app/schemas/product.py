from enum import Enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProductType(str, Enum):
    COIN = "COIN"
    PLAYER = "PLAYER"
    MANAGER = "MANAGER"


class CoinPackageScope(str, Enum):
    ALL = "ALL"
    ANDROID = "ANDROID"
    JAPAN = "JAPAN"
    TURKEY = "TURKEY"


class CoinPackageCreate(BaseModel):
    product_type: ProductType = ProductType.COIN
    coin_amount: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    price_uzs: float = Field(gt=0)
    scope: CoinPackageScope = CoinPackageScope.ALL
    is_active: bool = True

    @model_validator(mode="after")
    def validate_product_fields(self):
        if self.product_type == ProductType.COIN:
            if self.coin_amount is None:
                raise ValueError("coin_amount is required for coin products")
            self.name = None
        else:
            if not str(self.name or "").strip():
                raise ValueError("name is required for player and manager products")
            self.name = str(self.name).strip()
            self.coin_amount = None
            self.scope = CoinPackageScope.ALL
        return self


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
    product_type: ProductType
    name: str | None
    coin_amount: int | None
    price_uzs: float
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProductCreate(BaseModel):
    title: str
    category: str
    platform: Optional[str] = None
    region: Optional[str] = None
    product_type: ProductType = ProductType.COIN
    coins_amount: Optional[int] = None
    price_uzs: float
    description: Optional[str] = None
    order_index: Optional[int] = 0

    @model_validator(mode="after")
    def validate_product_type(self):
        if self.product_type == ProductType.COIN and not self.coins_amount:
            raise ValueError("coins_amount is required for coin products")
        if self.product_type != ProductType.COIN:
            self.coins_amount = None
        return self


class ProductUpdate(BaseModel):
    title: Optional[str] = None
    category: Optional[str] = None
    platform: Optional[str] = None
    region: Optional[str] = None
    product_type: Optional[ProductType] = None
    coins_amount: Optional[int] = None
    price_uzs: Optional[float] = None
    description: Optional[str] = None
    order_index: Optional[int] = None
    is_active: Optional[bool] = None


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    platform: Optional[str]
    region: Optional[str]
    product_type: ProductType
    coins_amount: Optional[int]
    price_uzs: float
    description: Optional[str]
    order_index: int
    is_active: bool
