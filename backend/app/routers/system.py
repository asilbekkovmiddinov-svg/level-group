from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db

router = APIRouter(
    prefix="/system",
    tags=["System"]
)


@router.post("/migrate-orders")
def migrate_orders(db: Session = Depends(get_db)):
    queries = [
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS claimed_by BIGINT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS completed_by BIGINT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS rejected_by BIGINT",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS reject_reason VARCHAR(255)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS processing_seconds INTEGER",
    ]

    for query in queries:
        db.execute(text(query))

    db.commit()

    return {
        "message": "Orders table migrated successfully"
    }
