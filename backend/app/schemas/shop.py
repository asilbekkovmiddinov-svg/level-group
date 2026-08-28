from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


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


class MiniAppBuyEFCRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    efc_amount: Decimal = Field(gt=0)


class MiniAppBuyArenaTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(gt=0)


class MiniAppShopSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    efc_price_uzs: Decimal = Field(gt=0)
    ticket_price_efc: Decimal = Field(gt=0)


class ShopCatalogResponse(BaseModel):
    efc_price_uzs: float
    ticket_price_efc: float
    max_efc_per_purchase: int
    max_tickets_per_purchase: int
    efc_balance: float
    uzs_balance: float
    ticket_balance: int


class ShopPurchaseResponse(BaseModel):
    purchase_id: int
    purchase_type: str
    status: str
    efc_amount: float | None
    ticket_quantity: int | None
    uzs_cost: float | None
    efc_cost: float | None
    efc_balance: float
    uzs_balance: float
    ticket_balance: int
    created_at: datetime


class ShopSettingsResponse(BaseModel):
    efc_price_uzs: float | None
    ticket_price_efc: float | None
    configured: bool
    updated_by: int | None
    updated_at: datetime
