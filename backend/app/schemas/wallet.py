from decimal import Decimal

from pydantic import BaseModel


class AddEFC(BaseModel):
    telegram_id: int
    amount: Decimal
