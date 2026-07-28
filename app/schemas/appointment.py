from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class AppointmentBook(BaseModel):
    contact_id: int
    datetime: datetime
    notes: Optional[str] = None

class AppointmentResponse(BaseModel):
    id: int
    contact_id: int
    user_id: int
    datetime: datetime
    status: str
    notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class SlotResponse(BaseModel):
    datetime: datetime
    formatted_time: str

class AvailabilityDay(BaseModel):
    day_of_week: int
    start_time: str  # formato "HH:MM"
    end_time: str    # formato "HH:MM"

class AvailabilityUpdate(BaseModel):
    days: List[AvailabilityDay]

