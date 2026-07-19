from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.routers.internal_wallet import require_internal_api_key
from app.schemas.campaign_delivery import (
    CampaignStatisticsResponse, DeliveryClaimResponse, DeliveryFailedRequest,
    DeliveryResultResponse, DeliverySentRequest,
)
from app.services import campaign_delivery


router = APIRouter(
    prefix="/internal/campaigns", tags=["Internal Campaign Delivery"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.post("/recipients/claim", response_model=list[DeliveryClaimResponse])
def claim_recipients(db: Session = Depends(get_db)):
    return campaign_delivery.claim(db)


def _result(recipient, final: bool):
    return {
        "recipient_id": recipient.id, "campaign_id": recipient.campaign_id,
        "status": recipient.status, "sent_at": recipient.sent_at,
        "failed_at": recipient.failed_at, "retry_count": recipient.retry_count,
        "final": final,
    }


@router.post("/recipients/{recipient_id}/sent", response_model=DeliveryResultResponse)
def mark_sent(recipient_id: int, data: DeliverySentRequest, db: Session = Depends(get_db)):
    return _result(*campaign_delivery.sent(db, recipient_id, data))


@router.post("/recipients/{recipient_id}/failed", response_model=DeliveryResultResponse)
def mark_failed(recipient_id: int, data: DeliveryFailedRequest, db: Session = Depends(get_db)):
    return _result(*campaign_delivery.failed(db, recipient_id, data))


@router.post("/{campaign_id}/recalculate", response_model=CampaignStatisticsResponse)
def recalculate(campaign_id: int, db: Session = Depends(get_db)):
    campaign = campaign_delivery.recalculate(db, campaign_id)
    sent_count = campaign.sent_count
    return {
        "campaign_id": campaign.id, "sent_count": sent_count,
        "opened_count": campaign.opened_count, "clicked_count": campaign.clicked_count,
        "failed_count": campaign.failed_count,
        "ctr": round(campaign.clicked_count / sent_count * 100, 2) if sent_count else 0.0,
        "failure_rate": round(campaign.failed_count / sent_count * 100, 2) if sent_count else 0.0,
    }
