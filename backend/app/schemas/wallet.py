from pydantic import BaseModel


class WalletResponse(BaseModel):
    telegram_id: int
    efc_balance: float
    uzs_balance: float
    locked_efc: float
    locked_uzs: float

    class Config:
        from_attributes = True
