from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.runtime import validate_startup_settings
validate_startup_settings()

from app.core.database import create_tables, SessionLocal
from app.core.migrations import run_migrations
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
from app.core.observability import configure_logging, correlation_middleware


configure_logging()
app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0",
)
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


@app.get("/")
def root():
    return {
        "status": "online",
        "project": "LEVEL_GROUP",
        "version": "1.0.0",
    }
