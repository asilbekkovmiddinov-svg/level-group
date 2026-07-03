from fastapi import APIRouter

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


@router.get("/ping")
def ping():
    return {
        "status": "ok",
        "message": "LEVEL_GROUP Backend is running!"
    }
