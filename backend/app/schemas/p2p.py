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


class P2PResponse(BaseModel):
    id: int

    owner_id: int
    order_type: str

    efc_amount: float
    remaining_efc: float

    min_trade_efc: float
    price_uzs: float

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

    status: str

    class Config:
        from_attributes = True
