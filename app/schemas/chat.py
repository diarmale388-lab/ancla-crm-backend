from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.base import SenderType, ChannelType, MessageType, MessageStatus

class MessageSend(BaseModel):
    content: str
    message_type: MessageType = MessageType.TEXT
    channel: Optional[ChannelType] = None

class MessageResponse(BaseModel):
    id: int
    contact_id: int
    sender_type: SenderType
    sender_id: Optional[int] = None
    channel: ChannelType
    message_type: MessageType
    content: str
    status: MessageStatus
    external_message_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class BitacoraNoteMini(BaseModel):
    id: Optional[int] = None
    note_type: Optional[str] = None
    content: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[str] = None
    author_name: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ContactChatResponse(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: str
    source: Optional[str] = None
    assigned_user_id: Optional[int] = None
    assigned_user_name: Optional[str] = None
    chatbot_enabled: bool
    avatar_url: Optional[str] = None
    interest_product: Optional[str] = None
    qualification_level: Optional[str] = None
    qualification_notes: Optional[str] = None
    pipeline_stage_id: Optional[int] = None
    lot_status: Optional[str] = None
    lot_city: Optional[str] = None
    client_type: Optional[str] = None
    created_at: Optional[datetime] = None
    quoted_value: Optional[float] = None
    estimated_budget: Optional[float] = None
    preferred_contact_method: Optional[str] = None
    advisor_status: Optional[str] = None
    last_bitacora_note: Optional[BitacoraNoteMini] = None
    last_message_content: Optional[str] = None
    last_message_time: Optional[datetime] = None
    last_message_sender: Optional[str] = None

    class Config:
        from_attributes = True


class AssignRequest(BaseModel):
    assigned_user_id: Optional[int] = None

class CorrectionCreate(BaseModel):
    query: str
    corrected_response: str
    message_id: Optional[int] = None

class CorrectionResponse(BaseModel):
    id: int
    contact_id: int
    query: str
    corrected_response: str
    is_approved: bool
    created_at: datetime

    class Config:
        from_attributes = True
