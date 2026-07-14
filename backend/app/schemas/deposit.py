from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from typing import Optional


class DepositCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Decimal


class InternalDepositCreate(DepositCreate):
    telegram_id: int


class DepositAdminAction(BaseModel):
    admin_id: int
    receipt_revision: int | None = None


class DepositReject(BaseModel):
    admin_id: int
    reason: Optional[str] = "Sabab ko'rsatilmagan"
