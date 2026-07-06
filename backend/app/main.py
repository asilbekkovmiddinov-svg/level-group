from fastapi import FastAPI

from app.core.database import create_tables, engine
from app.core.migrations import run_migrations
import app.models

from app.models.p2p import P2POrder, P2PTrade

from app.routers.auth import router as auth_router
from app.routers.user import router as user_router
from app.routers.wallet import router as wallet_router
from app.routers.transaction import router as transaction_router
from app.routers.deposit import router as deposit_router
from app.routers.withdraw import router as withdraw_router
from app.routers.product import router as product_router
from app.routers.order import router as order_router
from app.routers.p2p import router as p2p_router
from app.routers.system import router as system_router


def reset_p2p_tables_once():
    P2PTrade.__table__.drop(bind=engine, checkfirst=True)
    P2POrder.__table__.drop(bind=engine, checkfirst=True)

    P2POrder.__table__.create(bind=engine, checkfirst=True)
    P2PTrade.__table__.create(bind=engine, checkfirst=True)


app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0",
)

create_tables()
run_migrations()
reset_p2p_tables_once()

app.include_router(auth_router)
app.include_router(user_router)
app.include_router(wallet_router)
app.include_router(transaction_router)
app.include_router(deposit_router)
app.include_router(withdraw_router)
app.include_router(product_router)
app.include_router(order_router)
app.include_router(p2p_router)
app.include_router(system_router)


@app.get("/")
def root():
    return {
        "status": "online",
        "project": "LEVEL_GROUP",
        "version": "1.0.0",
    }
