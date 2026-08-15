import hashlib
from uuid import uuid4
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core import config
from app.core.database import get_db
from app.core.admin_auth import require_promotions_admin
from app.core.arena_internal_auth import require_arena_internal_api_key
from app.core.telegram_auth import TelegramUser, get_current_telegram_user
from app.models.arena_v3 import (
    ArenaV3Match,
    ArenaV3Status,
    ArenaV4AdminReviewStatus,
    ArenaV4ReviewType,
)
from app.models.user import User
from app.repositories.arena_v3 import ArenaV3Repository
from app.schemas.arena_v3 import (
    ArenaV3AppealDecisionRequest, ArenaV3AppealRequest,
    ArenaV3AppealResponse, ArenaV3CancelRequest, ArenaV3ConfigResponse,
    ArenaV3CreateRequest, ArenaV3FoundationResponse, ArenaV3JoinRequest,
    ArenaV3AIReviewResponse,
    ArenaV3MatchListResponse, ArenaV3MatchResponse, ArenaV3ActiveMatchResponse,
    ArenaV3RankingResponse, ArenaV3ResultResponse,
    ArenaV3RankingPrizeResponse, ArenaV3RankingPrizeUpdateRequest,
    ArenaV3ReadyRequest, ArenaV3RoomCodeRequest, ArenaV3ScreenshotListResponse,
    ArenaV3ScreenshotResponse,
    ArenaV4AdminCancelRequest, ArenaV4AdminClaimRequest,
    ArenaV4AdminDecisionRequest,
    ArenaV4AdminReviewDetailResponse, ArenaV4AdminReviewListResponse,
    ArenaV4AdminReviewResponse,
    ArenaV4AppealRequest, ArenaV4AppealResponse,
    ArenaV4AppealReviewRequest,
    ArenaV4ResultConfirmationResponse,
)
from app.services.arena_v3 import (
    ArenaV3FoundationOnly,
    ArenaV3Service,
    ArenaV3ServiceError,
    SCREENSHOT_UPLOAD_WINDOW_SECONDS,
)
from app.services.arena_v3_evidence import (
    MAX_APPEAL_VIDEO_SIZE,
    MAX_SCREENSHOT_SIZE,
    validate_appeal_video,
    validate_screenshot,
)
from app.services.object_storage import (
    StorageConfigurationError,
    StorageOperationError,
    delete_object,
    upload_object,
)
from app.services.arena_v4_admin_review import ArenaV4AdminReviewService
from app.services.telegram_notifications import (
    TelegramNotificationConfigError, TelegramNotificationTemporaryError,
    send_admin_message, send_deposit_receipt_photo,
    send_arena_appeal_video,
)


router = APIRouter(prefix="/arena", tags=["Arena V3"])
internal_router = APIRouter(prefix="/internal/arena", tags=["Arena V3 Internal"])
admin_router = APIRouter(prefix="/admin/arena", tags=["Arena V3 Admin"])


def require_arena_v3_access(
    current_user: TelegramUser = Depends(get_current_telegram_user),
) -> TelegramUser:
    allowed = config.ARENA_V3_ALLOWED_TELEGRAM_IDS
    if not config.ARENA_V3_ENABLED and current_user.telegram_id not in allowed:
        raise HTTPException(status_code=404, detail="Arena V3 is not enabled")
    return current_user


def require_idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if not value or not value.strip() or len(value.strip()) > 128:
        raise HTTPException(status_code=400, detail="Valid Idempotency-Key is required")
    return value.strip()


def foundation_call(callback):
    try:
        return callback()
    except ArenaV3FoundationOnly as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))


def core_match_call(callback):
    try:
        return callback()
    except ArenaV3ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))


@internal_router.get(
    "/reviews", response_model=ArenaV4AdminReviewListResponse
)
def internal_admin_review_list(
    review_status: ArenaV4AdminReviewStatus | None = Query(
        default=None, alias="status"
    ),
    review_type: ArenaV4ReviewType | None = Query(
        default=None, alias="review_type"
    ),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    reviews = ArenaV4AdminReviewService(db).list_reviews(
        status=review_status,
        review_type=review_type,
        limit=limit,
        offset=offset,
    )
    return {"reviews": reviews}


@internal_router.post(
    "/matches/{match_id}/score", response_model=ArenaV4AdminReviewResponse
)
def internal_channel_score(
    match_id: int, payload: ArenaV4AdminDecisionRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(lambda: ArenaV4AdminReviewService(db).submit_channel_decision(
        match_id=match_id, admin_id=payload.admin_id, payload=payload,
        idempotency_key=idempotency_key,
    ))


@internal_router.post(
    "/matches/{match_id}/cancel", response_model=ArenaV4AdminReviewResponse
)
def internal_channel_cancel(
    match_id: int, payload: ArenaV4AdminCancelRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(lambda: ArenaV4AdminReviewService(db).submit_channel_cancel(
        match_id=match_id, admin_id=payload.admin_id, payload=payload,
        idempotency_key=idempotency_key,
    ))


@internal_router.get(
    "/reviews/{review_id}", response_model=ArenaV4AdminReviewDetailResponse
)
def internal_admin_review_detail(
    review_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(
        lambda: ArenaV4AdminReviewService(db).detail(review_id)
    )


@internal_router.post(
    "/reviews/{review_id}/claim", response_model=ArenaV4AdminReviewResponse
)
def internal_admin_review_claim(
    review_id: int,
    payload: ArenaV4AdminClaimRequest,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(
        lambda: ArenaV4AdminReviewService(db).claim(
            review_id=review_id, admin_id=payload.admin_id
        )
    )


@internal_router.post(
    "/reviews/{review_id}/decision", response_model=ArenaV4AdminReviewResponse
)
def internal_admin_review_decision(
    review_id: int,
    payload: ArenaV4AdminDecisionRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(
        lambda: ArenaV4AdminReviewService(db).submit_decision(
            review_id=review_id,
            admin_id=payload.admin_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
    )


@internal_router.post(
    "/reviews/{review_id}/cancel", response_model=ArenaV4AdminReviewResponse
)
def internal_admin_review_cancel(
    review_id: int,
    payload: ArenaV4AdminCancelRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(
        lambda: ArenaV4AdminReviewService(db).submit_cancel(
            review_id=review_id,
            admin_id=payload.admin_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
    )


@internal_router.post(
    "/reviews/{review_id}/appeal-decision",
    response_model=ArenaV4AdminReviewResponse,
)
def internal_appeal_review_decision(
    review_id: int,
    payload: ArenaV4AppealReviewRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    from app.services.arena_v4_appeal_review import (
        ArenaV4AppealReviewService,
    )
    return core_match_call(
        lambda: ArenaV4AppealReviewService(db).submit(
            review_id=review_id,
            admin_id=payload.admin_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
    )


@router.get("/config", response_model=ArenaV3ConfigResponse)
def arena_v3_config(_: TelegramUser = Depends(require_arena_v3_access)):
    return {
        "enabled": config.ARENA_V3_ENABLED,
        "create_enabled": config.ARENA_V3_CREATE_ENABLED,
        "ai_enabled": config.ARENA_V3_AI_ENABLED,
        "settlement_enabled": config.ARENA_V3_SETTLEMENT_ENABLED,
        "match_time_minutes": list(range(6, 16)),
        "penalties_required": True,
        "room_code_max_length": 8,
        "screenshot_deadline_seconds": SCREENSHOT_UPLOAD_WINDOW_SECONDS,
        "ticket_cost": 2,
    }


@router.post("/create", response_model=ArenaV3MatchResponse, status_code=201)
def create_match(
    payload: ArenaV3CreateRequest,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    if not config.ARENA_V3_CREATE_ENABLED:
        raise HTTPException(status_code=503, detail="Arena V3 create is disabled")
    return core_match_call(lambda: ArenaV3Service(db).create_match(
        payload=payload, owner_id=current_user.telegram_id, idempotency_key=idempotency_key
    ))


@router.post("/{match_id}/join", response_model=ArenaV3MatchResponse)
def join_match(
    match_id: int,
    payload: ArenaV3JoinRequest,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    return core_match_call(lambda: ArenaV3Service(db).join_match(
        match_id=match_id, payload=payload, opponent_id=current_user.telegram_id,
        idempotency_key=idempotency_key,
    ))


@router.post("/{match_id}/ready", response_model=ArenaV3MatchResponse)
def ready(
    match_id: int, payload: ArenaV3ReadyRequest,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    return core_match_call(lambda: ArenaV3Service(db).ready(
        match_id=match_id, player_id=current_user.telegram_id, payload=payload
    ))


@router.post("/{match_id}/room-code", response_model=ArenaV3MatchResponse)
def submit_room_code(
    match_id: int, payload: ArenaV3RoomCodeRequest,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    return core_match_call(lambda: ArenaV3Service(db).submit_room_code(
        match_id=match_id, owner_id=current_user.telegram_id, payload=payload
    ))


@router.post("/{match_id}/upload-screenshot", response_model=ArenaV3ScreenshotResponse)
async def upload_screenshot(
    match_id: int,
    file: UploadFile = File(...),
    current_user: TelegramUser = Depends(require_arena_v3_access),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    service = ArenaV3Service(db)
    core_match_call(lambda: service.ensure_screenshot_upload_allowed(
        match_id=match_id, player_id=current_user.telegram_id
    ))
    content = await file.read(MAX_SCREENSHOT_SIZE + 1)
    metadata = core_match_call(lambda: validate_screenshot(
        file.filename, file.content_type, content
    ))
    file_hash = hashlib.sha256(content).hexdigest()
    match = db.get(ArenaV3Match, match_id)
    if match is None:
        raise HTTPException(404, "Arena match not found")
    if not config.ARENA_ADMIN_CHANNEL_ID:
        raise HTTPException(503, "Arena admin channel is not configured")
    if match.admin_channel_message_id is None:
        owner = db.get(User, match.owner_id)
        opponent = db.get(User, match.opponent_id)
        def player_line(label, user, efootball):
            display = " ".join(filter(None, [getattr(user, "first_name", None), getattr(user, "last_name", None)])) or "O‘yinchi"
            username = f"@{user.username}" if user and user.username else "—"
            return f"{label}: {display} | {username} | eFootball: {efootball or '—'}"
        match_lines = [
            f"🎮 Arena Match #{match.public_id}",
            player_line("Player A", owner, match.owner_efootball_username),
            player_line("Player B", opponent, match.opponent_efootball_username),
        ]
        if match.match_type == "DIVISION":
            match_lines.extend([
                "Mode: Global Division",
                "Entry: 1 Tournament Ticket per player",
                "Result: winner +3 points, loser 0 points",
                "Penalties: required",
            ])
        elif match.match_type == "TOURNAMENT":
            match_lines.extend([
                "Mode: Tournament",
                "Entry: 10 Tournament Tickets per player",
                "Result: tournament standings only; no EFC settlement",
                "Penalties: required",
            ])
        elif match.match_type == "STANDARD" and match.ticket_cost > 0:
            match_lines.extend([
                "Mode: Arena 1v1",
                f"Entry: {match.ticket_cost} Tournament Tickets per player",
                "Result: rating and statistics only; no EFC settlement",
                "Penalties: required",
            ])
        else:
            match_lines.extend([
                f"Stake: {match.stake_efc} EFC",
                f"Pot: {match.total_pool_efc} EFC",
                f"Platform fee: {match.commission_efc} EFC",
                f"Winner reward: {match.winner_reward_efc} EFC",
            ])
        text = "\n".join(match_lines)
        try:
            markup = {"inline_keyboard": [[
                {"text": "📝 Hisobni kiritish", "callback_data": f"arv4:match:score:{match.id}"},
                {"text": "❌ Bekor qilish", "callback_data": f"arv4:match:cancel:{match.id}"},
            ]]}
            post = await run_in_threadpool(
                send_admin_message, text, markup, config.ARENA_ADMIN_CHANNEL_ID
            )
        except (TelegramNotificationConfigError, TelegramNotificationTemporaryError) as exc:
            raise HTTPException(502, "Arena admin channel post failed") from exc
        match.admin_channel_message_id = post.message_id
        db.commit()
    label = "Screenshot A" if current_user.telegram_id == match.owner_id else "Screenshot B"
    try:
        telegram = await run_in_threadpool(
            send_deposit_receipt_photo, content, metadata.mime_type,
            file.filename or f"screenshot.{metadata.extension}", label,
            config.ARENA_ADMIN_CHANNEL_ID, None, match.admin_channel_message_id,
        )
    except (TelegramNotificationConfigError, TelegramNotificationTemporaryError) as exc:
        raise HTTPException(502, "Screenshot delivery to admin channel failed") from exc
    return core_match_call(lambda: service.upload_screenshot(
            match_id=match_id,
            player_id=current_user.telegram_id,
            idempotency_key=idempotency_key,
            storage_key=f"telegram:{telegram.file_id or telegram.message_id}",
            telegram_file_id=telegram.file_id or str(telegram.message_id),
            telegram_message_id=telegram.message_id,
            file_hash=file_hash,
            mime_type=metadata.mime_type,
            file_size=metadata.file_size,
            width=metadata.width,
            height=metadata.height,
        ))


@router.get(
    "/{match_id}/screenshots",
    response_model=ArenaV3ScreenshotListResponse,
)
def list_screenshots(
    match_id: int,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    screenshots = core_match_call(lambda: ArenaV3Service(db).list_screenshots(
        match_id=match_id, player_id=current_user.telegram_id
    ))
    return {"screenshots": screenshots}


@router.post("/{match_id}/video-appeal", response_model=ArenaV3AppealResponse)
async def submit_appeal(
    match_id: int,
    payload: ArenaV3AppealRequest = Depends(),
    video: UploadFile = File(...),
    current_user: TelegramUser = Depends(require_arena_v3_access),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    from app.services.arena_v3_appeals import (
        ensure_video_upload_allowed,
        submit_video_appeal,
    )
    existing = core_match_call(lambda: ensure_video_upload_allowed(
        db,
        match_id=match_id,
        player_id=current_user.telegram_id,
        idempotency_key=idempotency_key,
    ))
    if existing is not None:
        return existing
    content = await video.read(MAX_APPEAL_VIDEO_SIZE + 1)
    metadata = core_match_call(lambda: validate_appeal_video(
        video.filename, video.content_type, content
    ))
    file_hash = hashlib.sha256(content).hexdigest()
    storage_key = (
        f"arena/v3/{match_id}/appeals/"
        f"{current_user.telegram_id}/{uuid4()}.{metadata.extension}"
    )
    try:
        await run_in_threadpool(
            upload_object, storage_key, content, metadata.mime_type
        )
    except StorageConfigurationError as exc:
        raise HTTPException(503, "Appeal storage is not configured") from exc
    except StorageOperationError as exc:
        raise HTTPException(502, "Appeal storage upload failed") from exc
    try:
        return core_match_call(lambda: submit_video_appeal(
            db,
            match_id=match_id,
            player_id=current_user.telegram_id,
            payload=payload,
            idempotency_key=idempotency_key,
            storage_key=storage_key,
            file_hash=file_hash,
        ))
    except Exception:
        try:
            await run_in_threadpool(delete_object, storage_key)
        except (StorageConfigurationError, StorageOperationError):
            pass
        raise


@router.post("/{match_id}/appeal", response_model=ArenaV4AppealResponse)
async def submit_v4_appeal(
    match_id: int,
    payload: ArenaV4AppealRequest = Depends(),
    video: UploadFile = File(...),
    current_user: TelegramUser = Depends(require_arena_v3_access),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    from app.services.arena_v4_appeals import (
        ensure_v4_appeal_upload_allowed,
        submit_v4_video_appeal,
    )
    existing = core_match_call(lambda: ensure_v4_appeal_upload_allowed(
        db,
        match_id=match_id,
        player_id=current_user.telegram_id,
        idempotency_key=idempotency_key,
    ))
    if existing is not None:
        return existing
    content = await video.read(MAX_APPEAL_VIDEO_SIZE + 1)
    metadata = core_match_call(lambda: validate_appeal_video(
        video.filename, video.content_type, content
    ))
    file_hash = hashlib.sha256(content).hexdigest()
    match = db.get(ArenaV3Match, match_id)
    if match is None or match.admin_channel_message_id is None:
        raise HTTPException(409, "Arena channel post is not available")
    try:
        telegram = await run_in_threadpool(
            send_arena_appeal_video, content, metadata.mime_type,
            video.filename or f"appeal.{metadata.extension}",
            f"⚠ Appeal\nSabab: {payload.reason}",
            reply_to_message_id=match.admin_channel_message_id,
        )
    except (TelegramNotificationConfigError, TelegramNotificationTemporaryError) as exc:
        raise HTTPException(502, "Appeal delivery to admin channel failed") from exc
    return core_match_call(lambda: submit_v4_video_appeal(
            db,
            match_id=match_id,
            player_id=current_user.telegram_id,
            payload=payload,
            idempotency_key=idempotency_key,
            storage_key=f"telegram:{telegram.file_id or telegram.message_id}",
            file_hash=file_hash,
            telegram_file_id=telegram.file_id or str(telegram.message_id),
        ))


@router.post(
    "/{match_id}/confirm-result",
    response_model=ArenaV4ResultConfirmationResponse,
)
def confirm_v4_result(
    match_id: int,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    from app.services.arena_v4_result_confirmation import confirm_result

    return core_match_call(lambda: confirm_result(
        db,
        match_id=match_id,
        player_id=current_user.telegram_id,
        idempotency_key=idempotency_key,
    ))


@router.post("/{match_id}/cancel", response_model=ArenaV3MatchResponse)
def cancel_match(
    match_id: int, payload: ArenaV3CancelRequest,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
):
    return core_match_call(lambda: ArenaV3Service(db).cancel_match(
        match_id=match_id, player_id=current_user.telegram_id, payload=payload,
        idempotency_key=idempotency_key,
    ))


@router.get("/open", response_model=ArenaV3MatchListResponse)
def open_matches(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    matches = ArenaV3Service(db).repository.list_open(limit=limit, offset=offset)
    return {"matches": matches}


@router.get("/active", response_model=ArenaV3ActiveMatchResponse)
def active_match(
    current_user: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    return {
        "match": ArenaV3Service(db).repository.find_active_for_player(
            current_user.telegram_id
        )
    }


@router.post("/internal/{match_id}/start-ai-review", response_model=ArenaV3AIReviewResponse)
def start_ai_review(
    match_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(
        lambda: ArenaV3Service(db).start_ai_review(match_id=match_id)
    )


@internal_router.post("/{match_id}/start-ai", response_model=ArenaV3AIReviewResponse)
def internal_start_ai(
    match_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    return core_match_call(
        lambda: ArenaV3Service(db).start_ai_review(match_id=match_id)
    )


@internal_router.get("/{match_id}/ai-result", response_model=ArenaV3AIReviewResponse)
def internal_ai_result(
    match_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    review = ArenaV3Repository(db).get_latest_ai_review(match_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Arena V3 AI review not found")
    return review


@internal_router.post(
    "/{match_id}/appeal/decision",
    response_model=ArenaV3MatchResponse,
)
def internal_appeal_decision(
    match_id: int,
    payload: ArenaV3AppealDecisionRequest,
    idempotency_key: str = Depends(require_idempotency_key),
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    from app.services.arena_v3_appeals import resolve_appeal
    return core_match_call(lambda: resolve_appeal(
        db,
        match_id=match_id,
        payload=payload,
        idempotency_key=idempotency_key,
    ))


@router.post("/internal/{match_id}/finish", response_model=ArenaV3MatchResponse)
def finish_match(
    match_id: int,
    _: None = Depends(require_arena_internal_api_key),
    db: Session = Depends(get_db),
):
    if not config.ARENA_V3_SETTLEMENT_ENABLED:
        raise HTTPException(status_code=503, detail="Arena V3 settlement is disabled")
    return core_match_call(
        lambda: ArenaV3Service(db).finish_match(match_id=match_id)
    )


@router.get("/history", response_model=ArenaV3MatchListResponse)
def history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    matches = core_match_call(lambda: ArenaV3Service(db).history(
        player_id=current_user.telegram_id, limit=limit, offset=offset
    ))
    return {"matches": matches}


@router.get("/ranking", response_model=ArenaV3RankingResponse)
def ranking(
    period: str = Query("all", pattern="^(weekly|monthly|all)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    from app.services.arena_v3_ranking import get_ranking, get_ranking_prize
    return {
        "period": period,
        "prize_text": get_ranking_prize(db, period),
        "players": get_ranking(
            db, period=period, limit=limit, offset=offset
        ),
        "limit": limit,
        "offset": offset,
    }


@admin_router.get(
    "/ranking-prizes", response_model=list[ArenaV3RankingPrizeResponse]
)
def admin_ranking_prizes(
    _: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    from app.services.arena_v3_ranking import list_ranking_prizes

    rows = list_ranking_prizes(db)
    return [
        {
            "period": period,
            "prize_text": row.prize_text if row is not None else None,
            "updated_at": row.updated_at if row is not None else None,
        }
        for period, row in zip(("weekly", "monthly"), rows)
    ]


@admin_router.put(
    "/ranking-prizes/{period}", response_model=ArenaV3RankingPrizeResponse
)
def admin_update_ranking_prize(
    period: Literal["weekly", "monthly"],
    payload: ArenaV3RankingPrizeUpdateRequest,
    admin: TelegramUser = Depends(require_promotions_admin),
    db: Session = Depends(get_db),
):
    from app.services.arena_v3_ranking import update_ranking_prize

    return update_ranking_prize(
        db,
        period=period,
        prize_text=payload.prize_text,
        admin_id=admin.telegram_id,
    )


@router.get("/{match_id}/result", response_model=ArenaV3ResultResponse)
def match_result(
    match_id: int,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    repository = ArenaV3Repository(db)
    match = repository.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Arena V3 match not found")
    if current_user.telegram_id not in {match.owner_id, match.opponent_id}:
        raise HTTPException(status_code=403, detail="Player is not a match participant")
    return {
        "match": match,
        "ai_review": repository.get_latest_ai_review(match.id),
    }


@router.get("/{match_id}", response_model=ArenaV3MatchResponse)
def match_detail(
    match_id: int,
    current_user: TelegramUser = Depends(require_arena_v3_access),
    db: Session = Depends(get_db),
):
    match = ArenaV3Service(db).repository.get_match(match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Arena V3 match not found")
    if (
        match.status != ArenaV3Status.OPEN
        and current_user.telegram_id not in {match.owner_id, match.opponent_id}
    ):
        raise HTTPException(status_code=403, detail="Player is not a match participant")
    return match
