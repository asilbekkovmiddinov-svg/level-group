import hmac

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import MONETAG_POSTBACK_SECRET
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.schemas.wheel import MonetagRewardSessionCreate
from app.services import monetag_reward


router = APIRouter(prefix="/api/ads/monetag", tags=["Monetag Ads"])


@router.post("/session")
def create_monetag_session(
    payload: MonetagRewardSessionCreate,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        session = monetag_reward.create_reward_session(
            db,
            current_user.telegram_id,
            str(payload.ymid),
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))
    return {"ymid": session.ymid, "status": session.status, "expires_at": session.expires_at}


@router.get("/status/{ymid}")
def monetag_session_status(
    ymid: str,
    current_user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    session = monetag_reward.get_reward_status(db, current_user.telegram_id, ymid)
    if not session:
        raise HTTPException(status_code=404, detail="Reward sessiyasi topilmadi")
    return {"ymid": session.ymid, "status": session.status}


@router.get("/postback")
def monetag_postback(
    token: str = Query(default=""),
    ymid: str = Query(min_length=1, max_length=64),
    telegram_id: int = Query(gt=0),
    event: str | None = Query(default=None),
    value: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    sub: str | None = Query(default=None),
    price: str | None = Query(default=None),
    source: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    reward_event_type: str | None = Query(default=None),
    zone_id: str | None = Query(default=None),
    sub_zone_id: str | None = Query(default=None),
    estimated_price: str | None = Query(default=None),
    request_var: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if not MONETAG_POSTBACK_SECRET or not hmac.compare_digest(token, MONETAG_POSTBACK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Monetag postback token")

    resolved_event = event or event_type
    resolved_value = value or reward_event_type
    resolved_zone = zone or zone_id
    resolved_sub = sub or sub_zone_id
    resolved_price = price or estimated_price
    resolved_source = source or request_var
    if not resolved_event or not resolved_value or not resolved_source:
        raise HTTPException(status_code=422, detail="Missing Monetag postback parameters")

    try:
        session, rewarded = monetag_reward.process_postback(
            db,
            ymid=ymid,
            telegram_id=telegram_id,
            event=resolved_event,
            value=resolved_value,
            zone=resolved_zone,
            sub=resolved_sub,
            price=resolved_price,
            source=resolved_source,
        )
    except ValueError:
        db.rollback()
        return {"success": True, "rewarded": False}
    return {
        "success": True,
        "rewarded": rewarded,
        "status": session.status if session else "IGNORED",
    }
