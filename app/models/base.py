import datetime as dt_module
from enum import Enum as PyEnum
from typing import List, Optional
from sqlalchemy import (
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Enum,
    Float,
    Text,
    JSON,
    Time
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

class Base(DeclarativeBase):
    pass

class UserRole(str, PyEnum):
    ADMIN = "admin"
    ASESOR = "asesor"

class SenderType(str, PyEnum):
    USER = "user"
    CONTACT = "contact"
    SYSTEM = "system"
    AI = "ai"

class ChannelType(str, PyEnum):
    WHATSAPP = "whatsapp"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    SMS = "sms"
    SYSTEM = "system"

class MessageType(str, PyEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    VIDEO = "video"
    TEMPLATE = "template"

class MessageStatus(str, PyEnum):
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.ASESOR, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Para asignación Round Robin
    last_assigned_at: Mapped[Optional[dt_module.datetime]] = mapped_column(DateTime, nullable=True)
    
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, onupdate=dt_module.datetime.utcnow, nullable=False)
    
    # Credenciales de Google OAuth2 del asesor
    google_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_token_expiry: Mapped[Optional[dt_module.datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relaciones
    contacts: Mapped[List["Contact"]] = relationship(back_populates="assigned_user")
    messages: Mapped[List["Message"]] = relationship(back_populates="sender_user")
    availabilities: Mapped[List["Availability"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False) # Orden en el tablero Kanban
    
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)
    
    # Relaciones
    contacts: Mapped[List["Contact"]] = relationship(back_populates="pipeline_stage")


class Contact(Base):
    __tablename__ = "contacts"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False) # WhatsApp identifier / SMS
    source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # e.g. Meta Ads, WhatsApp Orgánico, etc.
    
    assigned_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    pipeline_stage_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pipeline_stages.id"), nullable=True)
    
    # Campos de integración de Meta
    meta_lead_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True) # Si vino de Meta Leads Form
    instagram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    facebook_page_scoped_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    whatsapp_phone_number_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Bot / IA "Kill Switch" para este chat específico
    chatbot_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Estado y memoria de agendamiento de citas
    scheduling_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    proposed_datetime: Mapped[Optional[dt_module.datetime]] = mapped_column(DateTime, nullable=True)

    # Maduración y Calificación Avanzada (ANCLA Special Projects)
    interest_product: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # Glamping, Flex Home, Frío, Bodegas
    qualification_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True) # VIP, Explorador, Curioso
    qualification_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Habeas Data (Colombia Ley 1581 de 2012)
    habeas_data_authorized: Mapped[Optional[bool]] = mapped_column(Boolean, default=None, nullable=True)
    habeas_data_authorized_at: Mapped[Optional[dt_module.datetime]] = mapped_column(DateTime, nullable=True)
    habeas_data_ip: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, onupdate=dt_module.datetime.utcnow, nullable=False)
    
    # Relaciones
    assigned_user: Mapped[Optional["User"]] = relationship(back_populates="contacts")
    pipeline_stage: Mapped[Optional["PipelineStage"]] = relationship(back_populates="contacts")
    messages: Mapped[List["Message"]] = relationship(back_populates="contact")
    appointments: Mapped[List["Appointment"]] = relationship(back_populates="contact", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    
    sender_type: Mapped[SenderType] = mapped_column(Enum(SenderType), nullable=False) # user, contact, system, ai
    sender_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True) # Solo si sender_type == USER
    
    channel: Mapped[ChannelType] = mapped_column(Enum(ChannelType), nullable=False) # whatsapp, instagram, etc.
    message_type: Mapped[MessageType] = mapped_column(Enum(MessageType), default=MessageType.TEXT, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MessageStatus] = mapped_column(Enum(MessageStatus), default=MessageStatus.SENT, nullable=False)
    
    # Id del mensaje en Meta/WhatsApp para control de duplicados y actualizaciones de estado
    external_message_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)
    
    # Relaciones
    contact: Mapped["Contact"] = relationship(back_populates="messages")
    sender_user: Mapped[Optional["User"]] = relationship(back_populates="messages")


class Campaign(Base):
    __tablename__ = "campaigns"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    meta_campaign_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False) # ACTIVE, PAUSED, etc.
    objective: Mapped[str] = mapped_column(String(100), nullable=False)
    
    budget: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leads_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Métricas de negocio calculadas
    cpl: Mapped[float] = mapped_column(Float, default=0.0, nullable=False) # Cost Per Lead
    cpa: Mapped[float] = mapped_column(Float, default=0.0, nullable=False) # Cost Per Action
    roas: Mapped[float] = mapped_column(Float, default=0.0, nullable=False) # Return on Ad Spend
    
    synced_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, onupdate=dt_module.datetime.utcnow, nullable=False)


class AutomationRule(Base):
    __tablename__ = "automation_rules"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(100), nullable=False) # e.g. "no_response_24h", "new_lead"
    action_type: Mapped[str] = mapped_column(String(100), nullable=False) # e.g. "send_sms", "send_whatsapp", "assign_user"
    action_payload: Mapped[dict] = mapped_column(JSON, nullable=False) # Ejemplo: {"template": "Hola, vimos que no respondiste..."}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, onupdate=dt_module.datetime.utcnow, nullable=False)


class Availability(Base):
    __tablename__ = "availabilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False) # 0 = Lunes, 6 = Domingo
    start_time: Mapped[dt_module.time] = mapped_column(Time, nullable=False) # Hora de entrada (ej. 09:00:00)
    end_time: Mapped[dt_module.time] = mapped_column(Time, nullable=False) # Hora de salida (ej. 17:00:00)

    # Relaciones
    user: Mapped["User"] = relationship(back_populates="availabilities")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    datetime: Mapped[dt_module.datetime] = mapped_column(DateTime, nullable=False) # Fecha y hora de la cita
    status: Mapped[str] = mapped_column(String(50), default="CONFIRMED", nullable=False) # PENDING, CONFIRMED, CANCELLED
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)

    # Relaciones
    contact: Mapped["Contact"] = relationship(back_populates="appointments")
    user: Mapped["User"] = relationship(back_populates="appointments")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)


class LeadActivityLog(Base):
    __tablename__ = "lead_activity_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True) # None = System/AI/Template Broadcast
    activity_type: Mapped[str] = mapped_column(String(100), nullable=False) # stage_change, appointment_booked, appointment_cancelled, message_sent, advisor_reassigned, chatbot_toggle, internal_note
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)


class UserInvitation(Base):
    __tablename__ = "user_invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.ASESOR, nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[dt_module.datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)


class HabeasDataConsentLog(Base):
    __tablename__ = "habeas_data_consent_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False)
    authorized: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    meta_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)


class AuditCorrection(Base):
    __tablename__ = "audit_corrections"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[Optional[int]] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_response: Mapped[str] = mapped_column(Text, nullable=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt_module.datetime] = mapped_column(DateTime, default=dt_module.datetime.utcnow, nullable=False)




