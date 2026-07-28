from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from app.models.base import UserRole

# Schema base para el Usuario
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: UserRole = UserRole.ASESOR
    is_active: bool = True
    avatar_url: Optional[str] = None

# Schema para la creación de un Usuario
class UserCreate(UserBase):
    password: str

# Schema para actualizar un Usuario
class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

class UserInDBBase(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

# Schema de respuesta al consultar un Usuario
class UserResponse(UserInDBBase):
    pass

# Esquemas de Tokens
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: Optional[int] = None

class InvitationCreate(BaseModel):
    email: EmailStr
    role: UserRole

class InvitationResponse(BaseModel):
    email: EmailStr
    role: UserRole
    token: str
    expires_at: datetime

class InvitedRegister(BaseModel):
    token: str
    full_name: str
    password: str

