from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime

class PipelineStageResponse(BaseModel):
    id: int
    name: str
    position: int

    class Config:
        from_attributes = True

class LeadStageUpdate(BaseModel):
    pipeline_stage_id: int

class LeadPipelineResponse(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: str
    email: Optional[str] = None
    source: Optional[str] = None
    pipeline_stage_id: Optional[int] = None
    assigned_user_id: Optional[int] = None
    assigned_user_name: Optional[str] = None
    interest_product: Optional[str] = None
    lot_status: Optional[str] = None
    lot_city: Optional[str] = None
    estimated_budget: Optional[float] = 0.0
    chatbot_enabled: bool = True
    last_message_content: Optional[str] = None
    last_message_time: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
