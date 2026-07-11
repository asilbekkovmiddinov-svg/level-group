from decimal import Decimal

from pydantic import BaseModel


class WithdrawCreate(BaseModel):
    telegram_id: int
    amount: Decimal
    card_number: str
    card_holder: str
    bank_name: str


class WithdrawAdminAction(BaseModel):
    admin_id: int


class WithdrawReject(BaseModel):
    admin_id: int
    reason: str = "Admin rad etdi"
