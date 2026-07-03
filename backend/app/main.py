from fastapi import FastAPI

from app.core.database import create_tables
import app.models

from app.routers.auth import router as auth_router
from app.routers.user import router as user_router

app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0"
)

create_tables()

app.include_router(auth_router)
app.include_router(user_router)


@app.get("/")
def root():
    return {
        "status": "online",
        "project": "LEVEL_GROUP",
        "version": "1.0.0"
    }
