from pydantic import BaseModel


class AddEFC(BaseModel):
    telegram_id: int
    amount: float
