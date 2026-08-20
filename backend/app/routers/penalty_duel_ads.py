import hmac

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core import config
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.wall_rush import active_penalty_duel_ad_providers
from app.schemas.wall_rush import TadsWebhookPayload, WallRushAdsgramRewardToken
from app.services import adsgram_reward
from app.services.penalty_duel_ads import PenaltyDuelAdError
from app.services.wall_rush import wallet_response


router = APIRouter(prefix="/penalty-duel/rewards", tags=["Penalty Duel Ads"])


@router.get("/config")
def rewarded_ad_config(
    _: TelegramUser = Depends(get_current_telegram_user),
):
    onclicka_enabled = config.onclicka_rewarded_ad_ready()
    tads_enabled = config.penalty_duel_tads_ready()
    telega_enabled = config.penalty_duel_telega_ready()
    return {
        "providers": list(active_penalty_duel_ad_providers(
            onclicka_enabled,
            tads_enabled=tads_enabled,
            telega_enabled=telega_enabled,
        )),
        "tads_widget_id": config.TADS_PENALTY_DUEL_WIDGET_ID if tads_enabled else "",
        "telega_token": (config.TELEGA_MINIAPP_TOKEN or "") if telega_enabled else "",
        "telega_ad_block_uuid": (
            config.TELEGA_REWARDED_AD_BLOCK_UUID if telega_enabled else ""
        ),
        "tads_enabled": tads_enabled,
        "telega_enabled": telega_enabled,
        "onclicka_enabled": onclicka_enabled,
        "onclicka_spot_id": config.ONCLICKA_SPOT_ID if onclicka_enabled else "",
    }


def _callback_user_id(
    USERID: int | None,
    user_id: int | None,
    telegram_id: int | None,
) -> int:
    values = {value for value in (USERID, user_id, telegram_id) if value is not None}
    if len(values) != 1:
        raise HTTPException(status_code=422, detail="Exactly one Telegram user id is required")
    value = values.pop()
    if value <= 0:
        raise HTTPException(status_code=422, detail="Invalid Telegram user id")
    return value


@router.post("/adsgram/session")
def create_adsgram_session(
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        session, token = adsgram_reward.create_penalty_duel_reward_session(
            db, user.telegram_id,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"session_id": session.id, "token": token, "expires_at": session.expires_at}


@router.post("/adsgram/claim")
def claim_adsgram(
    payload: WallRushAdsgramRewardToken,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        session, wallet = adsgram_reward.claim_penalty_duel_reward(
            db, user.telegram_id, payload.token,
        )
    except ValueError as error:
        db.rollback()
        message = str(error)
        status_code = 425 if "hali kelmadi" in message else 409
        raise HTTPException(status_code=status_code, detail=message) from error
    return {"success": True, "session_id": session.id, "wallet": wallet_response(wallet)}


@router.post("/adsgram/cancel")
def cancel_adsgram(
    payload: WallRushAdsgramRewardToken,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        session = adsgram_reward.cancel_penalty_duel_reward_session(
            db, user.telegram_id, payload.token,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "session_id": session.id, "status": session.status}


@router.post("/onclicka/session")
def create_onclicka_session(
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    if not config.onclicka_rewarded_ad_ready():
        raise HTTPException(status_code=503, detail="OnClickA rewarded ads are disabled")
    try:
        session, token = adsgram_reward.create_onclicka_penalty_duel_reward_session(
            db, user.telegram_id,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"session_id": session.id, "token": token, "expires_at": session.expires_at}


@router.post("/onclicka/cancel")
def cancel_onclicka_session(
    payload: WallRushAdsgramRewardToken,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        session = adsgram_reward.cancel_onclicka_penalty_duel_reward_session(
            db, user.telegram_id, payload.token,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "session_id": session.id, "status": session.status}


@router.post("/tads/webhook")
def tads_reward_webhook(
    payload: TadsWebhookPayload,
    secret: str = "",
    db: Session = Depends(get_db),
):
    if not config.TADS_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="TADS webhook is not configured")
    if not hmac.compare_digest(secret, config.TADS_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid TADS webhook secret")
    if not hmac.compare_digest(payload.widget_id, config.TADS_PENALTY_DUEL_WIDGET_ID):
        raise HTTPException(status_code=403, detail="Unknown TADS widget")
    try:
        telegram_id = int(payload.telegram_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Invalid telegram_id") from error
    try:
        completed = adsgram_reward.complete_tads_penalty_duel_reward(
            db, telegram_id,
        )
    except PenaltyDuelAdError as error:
        db.rollback()
        if "once per 5 minutes" in str(error):
            return {"status": "ok", "rewarded": False, "reason": "cooldown"}
        raise HTTPException(status_code=409, detail=str(error)) from error
    if completed is None:
        reason = (
            "duplicate" if adsgram_reward.has_recent_tads_penalty_duel_reward(
                db, telegram_id,
            ) else "no_pending_session"
        )
        return {"status": "ok", "rewarded": False, "reason": reason}
    _, wallet = completed
    return {"status": "ok", "rewarded": True, "wallet": wallet_response(wallet)}


@router.post("/tads/session")
def create_tads_session(
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    if not config.penalty_duel_tads_ready():
        raise HTTPException(status_code=503, detail="TADS rewarded ads are disabled")
    try:
        session, token = adsgram_reward.create_tads_penalty_duel_reward_session(
            db, user.telegram_id,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"session_id": session.id, "token": token, "expires_at": session.expires_at}


@router.post("/tads/cancel")
def cancel_tads_session(
    payload: WallRushAdsgramRewardToken,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        session = adsgram_reward.cancel_tads_penalty_duel_reward_session(
            db, user.telegram_id, payload.token,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "session_id": session.id, "status": session.status}


@router.get("/telega/callback")
def telega_reward_callback(
    secret: str = "",
    USERID: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    telegram_id: int | None = Query(default=None),
    ad_block_uuid: str = "",
    db: Session = Depends(get_db),
):
    if not config.TELEGA_REWARD_SECRET:
        raise HTTPException(status_code=503, detail="Telega reward callback is not configured")
    if not hmac.compare_digest(secret, config.TELEGA_REWARD_SECRET):
        raise HTTPException(status_code=401, detail="Invalid Telega reward secret")
    if not hmac.compare_digest(ad_block_uuid, config.TELEGA_REWARDED_AD_BLOCK_UUID):
        raise HTTPException(status_code=403, detail="Unknown Telega ad block")
    callback_user_id = _callback_user_id(USERID, user_id, telegram_id)
    try:
        completed = adsgram_reward.complete_telega_penalty_duel_reward(
            db, callback_user_id,
        )
    except PenaltyDuelAdError as error:
        db.rollback()
        if "once per 5 minutes" in str(error):
            return {"status": "ok", "rewarded": False, "reason": "cooldown"}
        raise HTTPException(status_code=409, detail=str(error)) from error
    if completed is None:
        reason = (
            "duplicate" if adsgram_reward.has_recent_telega_penalty_duel_reward(
                db, callback_user_id,
            ) else "no_pending_session"
        )
        return {"status": "ok", "rewarded": False, "reason": reason}
    _, wallet = completed
    return {"status": "ok", "rewarded": True, "wallet": wallet_response(wallet)}


@router.post("/telega/session")
def create_telega_session(
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    if not config.penalty_duel_telega_ready():
        raise HTTPException(status_code=503, detail="Telega.io rewarded ads are disabled")
    try:
        session, token = adsgram_reward.create_telega_penalty_duel_reward_session(
            db, user.telegram_id,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"session_id": session.id, "token": token, "expires_at": session.expires_at}


@router.post("/telega/cancel")
def cancel_telega_session(
    payload: WallRushAdsgramRewardToken,
    user: TelegramUser = Depends(get_current_telegram_user),
    db: Session = Depends(get_db),
):
    try:
        session = adsgram_reward.cancel_telega_penalty_duel_reward_session(
            db, user.telegram_id, payload.token,
        )
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"success": True, "session_id": session.id, "status": session.status}


@router.get("/onclicka/callback/{opaque_token}")
def onclicka_reward_callback(
    opaque_token: str,
    USERID: int = Query(gt=0),
    db: Session = Depends(get_db),
):
    if not config.onclicka_rewarded_ad_ready():
        raise HTTPException(status_code=503, detail="OnClickA rewarded ads are disabled")
    configured_token = (config.ONCLICKA_REWARD_SECRET or "").strip()
    if len(configured_token) < 32:
        raise HTTPException(status_code=503, detail="OnClickA reward callback is not configured")
    if not hmac.compare_digest(opaque_token, configured_token):
        raise HTTPException(status_code=401, detail="Invalid OnClickA reward secret")
    try:
        completed = adsgram_reward.complete_onclicka_penalty_duel_reward(db, USERID)
    except PenaltyDuelAdError as error:
        db.rollback()
        if "once per 5 minutes" in str(error):
            return {"status": "ok", "rewarded": False, "reason": "cooldown"}
        raise HTTPException(status_code=409, detail=str(error)) from error
    if completed is None:
        return {"status": "ok", "rewarded": False, "reason": "no_pending_session"}
    return {"status": "ok", "rewarded": True}
