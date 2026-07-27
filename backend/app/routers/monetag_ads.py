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
    event: str = Query(),
    value: str = Query(),
    zone: str | None = Query(default=None),
    sub: str | None = Query(default=None),
    price: str | None = Query(default=None),
    source: str = Query(),
    db: Session = Depends(get_db),
):
    if not MONETAG_POSTBACK_SECRET or not hmac.compare_digest(token, MONETAG_POSTBACK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Monetag postback token")
    try:
        session, rewarded = monetag_reward.process_postback(
            db,
            ymid=ymid,
            telegram_id=telegram_id,
            event=event,
            value=value,
            zone=zone,
            sub=sub,
            price=price,
            source=source,
        )
    except ValueError:
        db.rollback()
        return {"success": True, "rewarded": False}
    return {
        "success": True,
        "rewarded": rewarded,
        "status": session.status if session else "IGNORED",
    }
