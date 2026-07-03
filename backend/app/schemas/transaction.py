from pydantic import BaseModel
from typing import Optional


class TransactionResponse(BaseModel):
    id: int
    telegram_id: int
    currency: str
    amount: float
    balance_before: float
    balance_after: float
    type: str
    status: str
    description: Optional[str] = None

    class Config:
        from_attributes = True
