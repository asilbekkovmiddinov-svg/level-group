from typing import Optional

from pydantic import BaseModel, ConfigDict


class OrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: int
    region: Optional[str] = None
    platform: Optional[str] = None


class OrderReject(BaseModel):
    admin_id: int
    reason: Optional[str] = "Sabab ko'rsatilmagan"


class OrderAdminAction(BaseModel):
    admin_id: int
