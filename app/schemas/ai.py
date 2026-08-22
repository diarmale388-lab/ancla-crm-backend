from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class AICopilotRequest(BaseModel):
    contact_id: int

class AICopilotResponse(BaseModel):
    suggestion: str

class AICopyRequest(BaseModel):
    description: str
    tone: str

class AICopyResponse(BaseModel):
    headline: str
    body: str
    cta: str

class AIApprovalCreate(BaseModel):
    topic: str
    detected_question: str
    official_answer: str
    source: Optional[str] = "LEON_INVESTIGA"

class AIApprovalUpdate(BaseModel):
    topic: Optional[str] = None
    detected_question: Optional[str] = None
    official_answer: Optional[str] = None
    status: Optional[str] = None

class AIApprovalResponse(BaseModel):
    id: int
    topic: str
    source: str
    detected_question: str
    official_answer: str
    status: str
    approved_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

