from pydantic import BaseModel, ConfigDict, Field
from typing import Optional


class UserCreate(BaseModel):
    telegram_id: int
    first_name: str
    username: Optional[str] = None
    language: str = "uz"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    telegram_id: int
    first_name: str
    username: Optional[str] = None
    language: str
    is_banned: bool



class InternalUserRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_id: int = Field(gt=0)
    username: Optional[str] = Field(default=None, max_length=100)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    referral_code: Optional[str] = Field(default=None, max_length=24)
