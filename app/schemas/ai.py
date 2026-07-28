from pydantic import BaseModel

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
