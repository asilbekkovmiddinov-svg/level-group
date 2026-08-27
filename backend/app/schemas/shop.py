from decimal import Decimal

from pydantic import BaseModel, Field


class BuyEFCRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    efc_amount: Decimal = Field(gt=0)


class BuyArenaTicketRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
