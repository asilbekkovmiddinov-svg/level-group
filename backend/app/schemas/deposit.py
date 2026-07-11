from decimal import Decimal

from pydantic import BaseModel
from typing import Optional


class DepositCreate(BaseModel):
    telegram_id: int
    amount: Decimal


class DepositAdminAction(BaseModel):
    admin_id: int


class DepositReject(BaseModel):
    admin_id: int
    reason: Optional[str] = "Sabab ko'rsatilmagan"
