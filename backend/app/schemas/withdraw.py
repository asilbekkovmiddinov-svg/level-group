from decimal import Decimal

from pydantic import BaseModel


class WithdrawCreate(BaseModel):
    amount: Decimal
    card_number: str
    card_holder: str
    bank_name: str

    class Config:
        extra = "forbid"


class InternalWithdrawCreate(WithdrawCreate):
    telegram_id: int


class WithdrawAdminAction(BaseModel):
    admin_id: int


class WithdrawReject(BaseModel):
    admin_id: int
    reason: str = "Admin rad etdi"
