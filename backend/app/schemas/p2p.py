from typing import Optional

from pydantic import BaseModel, Field


class P2PCreate(BaseModel):
    telegram_id: int
    order_type: str = Field(..., description="BUY yoki SELL")
    efc_amount: float
    price_uzs: float
    min_trade_efc: float
    response_minutes: int = 15


class P2PTradeCreate(BaseModel):
    telegram_id: int
    efc_amount: float


class P2PTradeAction(BaseModel):
    telegram_id: int


class P2PCancel(BaseModel):
    telegram_id: int


class P2PUpdatePrice(BaseModel):
    telegram_id: int
    price_uzs: float


class P2PUpdateAmount(BaseModel):
    telegram_id: int
    efc_amount: float


class P2PUpdateMinTrade(BaseModel):
    telegram_id: int
    min_trade_efc: float


class P2PUpdateResponseMinutes(BaseModel):
    telegram_id: int
    response_minutes: int = Field(ge=5, le=60)
class P2PResponse(BaseModel):
    id: int

    owner_id: int
    order_type: str

    efc_amount: float
    remaining_efc: float

    min_trade_efc: float
    price_uzs: float

    response_minutes: int

    status: str

    class Config:
        from_attributes = True


class P2PTradeResponse(BaseModel):
    id: int

    order_id: int

    owner_id: int
    requester_id: int

    order_type: str

    efc_amount: float
    price_uzs: float

    total_uzs: float

    efc_fee: float
    uzs_fee: float

    owner_status: str
    requester_status: str

    status: str

    owner_expires_at: Optional[str] = None
    requester_expires_at: Optional[str] = None

    timeout_stage: Optional[str] = None

    class Config:
        from_attributes = True
    class P2PHistoryResponse(BaseModel):
    trade_id: int

    order_type: str

    status: str

    efc_amount: float
    total_uzs: float

    efc_fee: float
    uzs_fee: float

    created_at: str


class P2PMyOrdersResponse(BaseModel):
    id: int

    order_type: str

    remaining_efc: float

    price_uzs: float

    response_minutes: int

    status: str


class P2PRemainingTimeResponse(BaseModel):
    remaining_seconds: int
    remaining_text: str
