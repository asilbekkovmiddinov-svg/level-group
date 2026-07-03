from pydantic import BaseModel


class DepositCreate(BaseModel):
    telegram_id: int
    amount: float
