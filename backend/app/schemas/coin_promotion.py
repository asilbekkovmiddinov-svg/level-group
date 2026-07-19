from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CoinPromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class CoinPromotionFields(BaseModel):
    coin_package_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=160)
    original_price: float = Field(gt=0)
    promotion_price: float = Field(gt=0)
    total_quantity: int = Field(gt=0)
    per_user_limit: int = Field(default=1, gt=0)
    start_at: datetime
    end_at: datetime

    @model_validator(mode="after")
    def validate_contract(self):
        if self.promotion_price >= self.original_price:
            raise ValueError("promotion_price must be less than original_price")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class CoinPromotionCreate(CoinPromotionFields):
    pass


class CoinPromotionUpdate(CoinPromotionFields):
    pass


class CoinPackageResponse(BaseModel):
    id: int
    title: str
    category: str
    coin_amount: int
    price: float


class CoinPromotionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    coin_package_id: int
    coin_package: CoinPackageResponse
    title: str
    original_price: float
    promotion_price: float
    total_quantity: int
    reserved_quantity: int
    sold_quantity: int
    remaining_quantity: int
    per_user_limit: int
    status: CoinPromotionStatus
    start_at: datetime
    end_at: datetime
    created_at: datetime
    updated_at: datetime
