from pydantic import BaseModel
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
