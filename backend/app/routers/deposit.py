from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.deposit import create_deposit, get_deposits, approve_deposit
from app.schemas.deposit import DepositCreate

router = APIRouter(
    prefix="/deposit",
    tags=["Deposit"]
)


@router.post("/create")
def create_deposit_request(
    data: DepositCreate,
    db: Session = Depends(get_db)
):
    deposit = create_deposit(db, data)

    return {
        "message": "Deposit request created",
        "deposit_id": deposit.id,
        "telegram_id": deposit.telegram_id,
        "amount": float(deposit.amount),
        "status": deposit.status
    }


@router.get("/all")
def all_deposits(db: Session = Depends(get_db)):
    return get_deposits(db)


@router.post("/approve/{deposit_id}")
def approve_deposit_request(
    deposit_id: int,
    admin_id: int,
    db: Session = Depends(get_db)
):
    deposit = approve_deposit(db, deposit_id, admin_id)

    if not deposit:
        return {
            "message": "Deposit not found"
        }

    return {
        "message": "Deposit approved",
        "deposit_id": deposit.id,
        "status": deposit.status,
        "approved_by": deposit.approved_by
    }
