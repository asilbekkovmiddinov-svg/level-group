from decimal import Decimal

from pydantic import BaseModel, Field


class BuyEFCRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    efc_amount: Decimal = Field(gt=0)


class BuyArenaTicketRequest(BaseModel):
    telegram_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class ShopSettingsUpdate(BaseModel):
    admin_id: int = Field(gt=0)
    efc_price_uzs: Decimal = Field(gt=0)
    ticket_price_efc: Decimal = Field(gt=0)
