from pydantic import BaseModel


class WithdrawCreate(BaseModel):
    telegram_id: int
    amount: float
