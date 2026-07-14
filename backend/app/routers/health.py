from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.observability import metrics_snapshot
from app.routers.internal_wallet import require_internal_api_key
from app.models.deposit import Deposit
from app.models.withdraw import Withdraw

router = APIRouter()

@router.get("/health")
def health(db: Session = Depends(get_db)):
    try: db.execute(text("SELECT 1"))
    except Exception: raise HTTPException(503, "Database unavailable")
    return {
        "status": "ok",
        "project": "LEVEL_GROUP", "database": "ok"
    }

@router.get("/metrics")
def metrics(_: None = Depends(require_internal_api_key), db: Session = Depends(get_db)):
    stats = metrics_snapshot()
    for status, count in db.query(Deposit.receipt_notification_status, func.count(Deposit.id)).group_by(Deposit.receipt_notification_status).all():
        stats[f"receipt_notification_state_{status.lower()}"] = count
    stats["receipt_notification_attempts_total"] = db.query(func.coalesce(func.sum(Deposit.receipt_notification_attempts), 0)).scalar()
    stats["withdraw_notification_attempts_total"] = db.query(func.coalesce(func.sum(Withdraw.notification_attempts), 0)).scalar()
    stats["receipt_uploads_total"] = db.query(func.count(Deposit.id)).filter(Deposit.receipt_object_key.isnot(None)).scalar()
    return {"metrics": stats}
