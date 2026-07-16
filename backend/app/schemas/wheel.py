from pydantic import BaseModel, ConfigDict


class WheelSpinRequest(BaseModel):
    telegram_id: int
    spin_type: str  # FREE | AD | BONUS


class WheelSpinResponse(BaseModel):
    success: bool
    reward_code: str
    reward_type: str
    reward_amount: float
    message: str


class WheelDailyLimitResponse(BaseModel):
    free_spin_used: bool
    ad_spin_count: int
    bonus_spin_count: int
    next_ad_spin_at: str | None = None


class WheelCoinOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spin_id: int

    konami_login: str
    konami_password: str

    region: str
    platform: str


class WheelCoinOrderResponse(BaseModel):
    id: int

    telegram_id: int

    username: str | None = None
    first_name: str | None = None

    coin_amount: int

    konami_login: str | None = None
    region: str | None = None
    device: str | None = None

    status: str

    class Config:
        from_attributes = True
