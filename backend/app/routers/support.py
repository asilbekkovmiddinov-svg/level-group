import re

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import config


router = APIRouter(prefix="/support", tags=["Support"])
TELEGRAM_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")


class SupportConfigResponse(BaseModel):
    support_telegram_username: str | None


def normalize_support_username(value: str | None) -> str | None:
    username = str(value or "").strip().lstrip("@")
    return username if TELEGRAM_USERNAME_PATTERN.fullmatch(username) else None


@router.get("/config", response_model=SupportConfigResponse)
def get_support_config():
    return {
        "support_telegram_username": normalize_support_username(
            config.SUPPORT_TELEGRAM_USERNAME
        )
    }
