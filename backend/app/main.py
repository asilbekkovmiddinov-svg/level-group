from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.runtime import validate_startup_settings
validate_startup_settings()

from app.core.database import create_tables, engine, SessionLocal
from app.core.migrations import run_migrations
from app.core.arena_v3_migrations import run_arena_v3_migrations
from app.core.coin_chat_migration import run_coin_chat_migration
from app.core.seed_products import seed_products

import app.models

from app.routers.auth import router as auth_router
from app.routers.user import router as user_router
from app.routers.wallet import router as wallet_router
from app.routers.transaction import router as transaction_router
from app.routers.deposit import router as deposit_router
from app.routers.withdraw import router as withdraw_router
from app.routers.product import router as product_router
from app.routers.order import router as order_router
from app.routers.p2p import router as p2p_router
from app.routers.wheel import router as wheel_router
from app.routers.system import router as system_router
from app.routers.match import router as match_router
from app.routers.match_overview import router as match_overview_router
from app.routers.arena_v4 import router as arena_v4_router
from app.routers.arena_v3 import (
    internal_router as arena_v3_internal_router,
    router as arena_v3_router,
)
from app.routers.internal_wallet import router as internal_wallet_router
from app.routers.deposit_receipt import router as deposit_receipt_router
from app.routers.health import router as health_router
from app.routers.coin_order_chat import router as coin_order_chat_router
from app.routers.referral import router as referral_router
from app.routers.promotion import admin_router as promotion_admin_router
from app.routers.promotion import public_router as promotion_public_router
from app.routers.promotion_banner import router as promotion_banner_router
from app.routers.promotion_analytics import admin_router as promotion_analytics_admin_router
from app.routers.promotion_analytics import public_router as promotion_analytics_public_router
from app.routers.campaign import router as campaign_router
from app.routers.notification import router as notification_router
from app.routers.campaign_delivery import router as campaign_delivery_router
from app.routers.coin_promotion_admin import router as coin_promotion_admin_router
from app.routers.coin_package_admin import router as coin_package_admin_router
from app.routers.wheel_coin_order_admin import router as wheel_coin_order_admin_router
from app.routers.support import router as support_router
from app.routers.monetag_ads import router as monetag_ads_router
from app.routers.admin_metrics import router as admin_metrics_router
from app.core.observability import configure_logging, correlation_middleware
from app.core.config import (
    ARENA_V3_AI_ENABLED,
    ARENA_V3_ENABLED,
    CAMPAIGN_WORKER_ENABLED,
)
from app.services.campaign_worker import CampaignWorker
from app.services.coin_promotion_timeouts import CoinPromotionTimeoutWorker
from app.services.arena_timeouts import ArenaTimeoutWorker
from app.services.arena_v3_workers import ArenaV3AIWorker, ArenaV3ScreenshotTimeoutWorker
from app.services.arena_v3_notifications import ArenaV3NotificationWorker
from app.services.arena_v4_reward_release import ArenaV4RewardReleaseWorker


configure_logging()
campaign_worker = CampaignWorker(SessionLocal)
coin_promotion_timeout_worker = CoinPromotionTimeoutWorker(SessionLocal)
arena_timeout_worker = ArenaTimeoutWorker(SessionLocal)
arena_v3_timeout_worker = ArenaV3ScreenshotTimeoutWorker(SessionLocal)
arena_v3_ai_worker = ArenaV3AIWorker(SessionLocal)
arena_v3_notification_worker = ArenaV3NotificationWorker(SessionLocal)
arena_v4_reward_release_worker = ArenaV4RewardReleaseWorker(SessionLocal)
app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0",
)


@app.on_event("startup")
def start_campaign_worker():
    if CAMPAIGN_WORKER_ENABLED:
        campaign_worker.start()
    coin_promotion_timeout_worker.start()
    arena_timeout_worker.start()
    arena_v3_timeout_worker.start()
    if ARENA_V3_AI_ENABLED:
        arena_v3_ai_worker.start()
    if ARENA_V3_ENABLED:
        arena_v3_notification_worker.start()
        arena_v4_reward_release_worker.start()


@app.on_event("shutdown")
def stop_campaign_worker():
    campaign_worker.stop()
    coin_promotion_timeout_worker.stop()
    arena_timeout_worker.stop()
    arena_v3_timeout_worker.stop()
    arena_v3_ai_worker.stop()
    arena_v3_notification_worker.stop()
    arena_v4_reward_release_worker.stop()
app.middleware("http")(correlation_middleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://miniapp-jocker7005.waw0.amvera.tech",
        "https://web.telegram.org",
        "https://telegram.org",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

create_tables()
run_migrations()
run_arena_v3_migrations(engine)
run_coin_chat_migration()

db = SessionLocal()

try:
    seed_products(db)
finally:
    db.close()

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(wallet_router)
app.include_router(transaction_router)
app.include_router(deposit_router)
app.include_router(withdraw_router)
app.include_router(product_router)
app.include_router(order_router)
app.include_router(p2p_router)
app.include_router(wheel_router)
app.include_router(system_router)
app.include_router(match_router)
app.include_router(match_overview_router)
app.include_router(arena_v4_router)
app.include_router(arena_v3_router)
app.include_router(arena_v3_internal_router)
app.include_router(internal_wallet_router)
app.include_router(deposit_receipt_router)
app.include_router(health_router)
app.include_router(coin_order_chat_router)
app.include_router(referral_router)
app.include_router(promotion_analytics_admin_router)
app.include_router(promotion_admin_router)
app.include_router(promotion_public_router)
app.include_router(promotion_banner_router)
app.include_router(promotion_analytics_public_router)
app.include_router(campaign_router)
app.include_router(notification_router)
app.include_router(campaign_delivery_router)
app.include_router(coin_promotion_admin_router)
app.include_router(coin_package_admin_router)
app.include_router(wheel_coin_order_admin_router)
app.include_router(support_router)
app.include_router(monetag_ads_router)
app.include_router(admin_metrics_router)


@app.get("/")
def root():
    return {
        "status": "online",
        "project": "LEVEL_GROUP",
        "version": "1.0.0",
    }
