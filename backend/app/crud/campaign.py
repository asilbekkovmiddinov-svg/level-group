from app.models.campaign import Campaign


def create_campaign(values: dict, actor_id: int) -> Campaign:
    return Campaign(**values, created_by=actor_id, updated_by=actor_id)


def update_campaign(campaign: Campaign, values: dict, actor_id: int) -> Campaign:
    for field, value in values.items():
        setattr(campaign, field, value)
    campaign.updated_by = actor_id
    return campaign
