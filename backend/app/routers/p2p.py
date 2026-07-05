from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.crud.p2p import (
    create_p2p_order,
    get_open_p2p_orders,
    get_p2p_order,
    reserve_p2p_order,
    complete_p2p_order,
    cancel_p2p_order,
)
from app.schemas.p2p import (
    P2PCreate,
    P2PReserve,
    P2PComplete,
    P2PCancel,
)

router = APIRouter(
    prefix="/p2p",
    tags=["P2P"],
)


def p2p_response(order):
    return {
        "id": order.id,
        "seller_id": order.seller_id,
        "buyer_id": order.buyer_id,
        "efc_amount": float(order.efc_amount),
        "price_uzs": float(order.price_uzs),
        "seller_fee_efc": float(order.seller_fee_efc),
        "buyer_fee_uzs": float(order.buyer_fee_uzs),
        "total_buyer_pay_uzs": float(order.total_buyer_pay_uzs),
        "seller_receive_uzs": float(order.seller_receive_uzs),
        "status": order.status,
    }


@router.post("/create")
def create_order(
    data: P2PCreate,
    db: Session = Depends(get_db),
):
    order = create_p2p_order(
        db=db,
        telegram_id=data.telegram_id,
        efc_amount=data.efc_amount,
        price_uzs=data.price_uzs,
    )

    if order == "insufficient_efc":
        return {"message": "EFC balans yetarli emas"}

    if not order:
        return {"message": "P2P order yaratilmadi"}

    response = p2p_response(order)
    response["message"] = "P2P order yaratildi"
    return response


@router.get("/open")
def open_orders(db: Session = Depends(get_db)):
    return [p2p_response(order) for order in get_open_p2p_orders(db)]


@router.get("/{order_id}")
def one_order(
    order_id: int,
    db: Session = Depends(get_db),
):
    order = get_p2p_order(db, order_id)

    if not order:
        return {"message": "P2P order topilmadi"}

    return p2p_response(order)
@router.post("/{order_id}/reserve")
def reserve_order(
    order_id: int,
    data: P2PReserve,
    db: Session = Depends(get_db),
):
    order = reserve_p2p_order(
        db=db,
        order_id=order_id,
        buyer_id=data.telegram_id,
    )

    if order == "not_open":
        return {"message": "Order ochiq emas"}

    if order == "own_order":
        return {"message": "O‘zingizning orderingizni sotib olmaysiz"}

    if not order:
        return {"message": "P2P order topilmadi"}

    response = p2p_response(order)
    response["message"] = "P2P order band qilindi"
    return response


@router.post("/{order_id}/complete")
def complete_order(
    order_id: int,
    data: P2PComplete,
    db: Session = Depends(get_db),
):
    order = complete_p2p_order(
        db=db,
        order_id=order_id,
        buyer_id=data.telegram_id,
    )

    if order == "not_reserved":
        return {"message": "Order band qilinmagan"}

    if order == "not_buyer":
        return {"message": "Bu order sizga tegishli emas"}

    if order == "insufficient_uzs":
        return {"message": "UZS balans yetarli emas"}

    if not order:
        return {"message": "P2P order topilmadi"}

    response = p2p_response(order)
    response["message"] = "P2P order yakunlandi"
    return response


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    data: P2PCancel,
    db: Session = Depends(get_db),
):
    order = cancel_p2p_order(
        db=db,
        order_id=order_id,
        telegram_id=data.telegram_id,
    )

    if order == "not_seller":
        return {"message": "Faqat sotuvchi bekor qila oladi"}

    if order == "cannot_cancel":
        return {"message": "Bu orderni bekor qilib bo‘lmaydi"}

    if not order:
        return {"message": "P2P order topilmadi"}

    response = p2p_response(order)
    response["message"] = "P2P order bekor qilindi"
    return response
