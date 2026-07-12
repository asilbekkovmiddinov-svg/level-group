from pydantic import BaseModel, Field
from typing import Optional


class UserCreate(BaseModel):
    telegram_id: int
    first_name: str
    username: Optional[str] = None
    language: str = "uz"


class UserResponse(BaseModel):
    telegram_id: int
    first_name: str
    username: Optional[str] = None
    language: str
    is_banned: bool

    class Config:
        from_attributes = True


class InternalUserRegister(BaseModel):
    telegram_id: int = Field(gt=0)
    username: Optional[str] = Field(default=None, max_length=100)
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)

    class Config:
        extra = "forbid"
