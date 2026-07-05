from pydantic import BaseModel


class P2PCreate(BaseModel):
    telegram_id: int
    efc_amount: float
    price_uzs: float


class P2PReserve(BaseModel):
    telegram_id: int


class P2PComplete(BaseModel):
    telegram_id: int


class P2PCancel(BaseModel):
    telegram_id: int


class P2PResponse(BaseModel):
    id: int
    seller_id: int
    buyer_id: int | None = None

    efc_amount: float
    price_uzs: float

    seller_fee_efc: float
    buyer_fee_uzs: float

    total_buyer_pay_uzs: float
    seller_receive_uzs: float

    status: str

    class Config:
        from_attributes = True
