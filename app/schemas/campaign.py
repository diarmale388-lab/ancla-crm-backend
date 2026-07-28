from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class CampaignCreate(BaseModel):
    name: str
    objective: str
    budget: float

class CampaignUpdate(BaseModel):
    status: str

class CampaignResponse(BaseModel):
    id: int
    meta_campaign_id: str
    name: str
    status: str
    objective: str
    budget: float
    spend: float
    impressions: int
    clicks: int
    leads_count: int
    cpl: float
    cpa: float
    roas: float
    synced_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
