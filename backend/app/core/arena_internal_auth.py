import hmac
from typing import Annotated

from fastapi import Header, HTTPException, status

from app.core import config


def require_arena_internal_api_key(
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Authenticate trusted Arena workers/admin services only."""
    expected_key = config.INTERNAL_API_KEY
    if (
        not expected_key
        or not x_internal_api_key
        or not hmac.compare_digest(x_internal_api_key, expected_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Arena internal authentication is required",
        )
