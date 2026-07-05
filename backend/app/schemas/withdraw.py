from pydantic import BaseModel


class WithdrawCreate(BaseModel):
    telegram_id: int
    amount: float


class WithdrawAdminAction(BaseModel):
    admin_id: int


class WithdrawReject(BaseModel):
    admin_id: int
    reason: str
