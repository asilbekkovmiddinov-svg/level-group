from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import create_tables, SessionLocal
from app.core.migrations import run_migrations
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


app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0",
)

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


@app.get("/")
def root():
    return {
        "status": "online",
        "project": "LEVEL_GROUP",
        "version": "1.0.0",
    }
