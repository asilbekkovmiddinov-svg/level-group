from decimal import Decimal

from pydantic import BaseModel
from typing import Optional


class DepositCreate(BaseModel):
    amount: Decimal

    class Config:
        extra = "forbid"


class InternalDepositCreate(DepositCreate):
    telegram_id: int


class DepositAdminAction(BaseModel):
    admin_id: int
    receipt_revision: int | None = None


class DepositReject(BaseModel):
    admin_id: int
    reason: Optional[str] = "Sabab ko'rsatilmagan"
