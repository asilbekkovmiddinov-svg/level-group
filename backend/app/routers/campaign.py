from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.admin_auth import require_promotions_admin
from app.core.database import get_db
from app.core.telegram_auth import TelegramUser
from app.schemas.campaign import CampaignCreate, CampaignResponse, CampaignUpdate
from app.services import campaigns


router = APIRouter(prefix="/admin/campaigns", tags=["Campaign Center"])


@router.post("", response_model=CampaignResponse, status_code=201)
def create_campaign(data: CampaignCreate, admin: TelegramUser = Depends(require_promotions_admin), db: Session = Depends(get_db)):
    return campaigns.create(db, data, admin.telegram_id)


@router.get("", response_model=list[CampaignResponse])
def list_campaigns(include_deleted: bool = False, _admin: TelegramUser = Depends(require_promotions_admin), db: Session = Depends(get_db)):
    return campaigns.list_campaigns(db, include_deleted)


@router.patch("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(campaign_id: int, data: CampaignUpdate, admin: TelegramUser = Depends(require_promotions_admin), db: Session = Depends(get_db)):
    return campaigns.update(db, campaign_id, data, admin.telegram_id)


@router.delete("/{campaign_id}", response_model=CampaignResponse)
def delete_campaign(campaign_id: int, admin: TelegramUser = Depends(require_promotions_admin), db: Session = Depends(get_db)):
    return campaigns.soft_delete(db, campaign_id, admin.telegram_id)


def lifecycle(action: str):
    def endpoint(campaign_id: int, admin: TelegramUser = Depends(require_promotions_admin), db: Session = Depends(get_db)):
        return campaigns.transition(db, campaign_id, action, admin.telegram_id)
    return endpoint


router.add_api_route("/{campaign_id}/pause", lifecycle("pause"), methods=["POST"], response_model=CampaignResponse)
router.add_api_route("/{campaign_id}/resume", lifecycle("resume"), methods=["POST"], response_model=CampaignResponse)
router.add_api_route("/{campaign_id}/cancel", lifecycle("cancel"), methods=["POST"], response_model=CampaignResponse)


@router.post("/{campaign_id}/restore", response_model=CampaignResponse)
def restore_campaign(campaign_id: int, admin: TelegramUser = Depends(require_promotions_admin), db: Session = Depends(get_db)):
    return campaigns.restore(db, campaign_id, admin.telegram_id)


@router.get("/{campaign_id}", response_model=CampaignResponse)
def campaign_detail(campaign_id: int, include_deleted: bool = False, _admin: TelegramUser = Depends(require_promotions_admin), db: Session = Depends(get_db)):
    return campaigns.detail(db, campaign_id, include_deleted)
