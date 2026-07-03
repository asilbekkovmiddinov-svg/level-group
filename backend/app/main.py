from fastapi import FastAPI
from app.routers.auth import router as auth_router

app = FastAPI(
    title="LEVEL_GROUP API",
    version="1.0.0"
)

app.include_router(auth_router)


@app.get("/")
def root():
    return {
        "status": "online",
        "project": "LEVEL_GROUP",
        "version": "1.0.0"
    }
