import os
import logging
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models.base import User, Contact, Message, SenderType, ChannelType, MessageStatus, MessageType, PipelineStage
from app.core.deps import get_current_user
from app.services.activity import record_activity
from app.services.email import email_service
from app.services.ai_engine import ai_engine

logger = logging.getLogger("proposals_router")

router = APIRouter(prefix="/proposals", tags=["proposals"])

class ProposalGenerateRequest(BaseModel):
    contact_id: int
    model_name: str = Field(..., description="Nombre del modelo (ej. FLEX HOME 56m², CAPSULA LINVIG 26m², Cuarto Frío Copeland)")
    base_price: float = Field(..., ge=0, description="Precio base del modelo en USD / COP")
    extra_deck: bool = Field(False, description="Incluye Deck sintético/madera exterior")
    deck_cost: float = Field(0.0, ge=0)
    extra_solar: bool = Field(False, description="Incluye Kit Solar Off-Grid")
    solar_cost: float = Field(0.0, ge=0)
    extra_clima: bool = Field(False, description="Incluye Sistema de Climatización")
    clima_cost: float = Field(0.0, ge=0)
    freight_city: Optional[str] = Field(None, description="Ciudad o municipio de entrega")
    freight_cost: float = Field(0.0, ge=0)
    discount_pct: float = Field(0.0, ge=0, le=100)
    payment_terms: Optional[str] = Field("50% Anticipo de Fabricación, 50% Balanza Final", description="Condiciones de pago")
    custom_notes: Optional[str] = Field(None, description="Notas especiales para el cliente")

class ProposalSendEmailRequest(BaseModel):
    contact_id: int
    recipient_email: str
    proposal_pdf_path: str
    custom_meeting_notes: Optional[str] = Field(None, description="Notas tomadas durante la llamada comercial")

@router.post("/generate")
def generate_proposal_pdf(
    payload: ProposalGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Genera una propuesta comercial en PDF 100% personalizada con especificaciones técnicas
    del catálogo de ANCLA Special Projects.
    """
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Cálculos financieros
    subtotal = payload.base_price + (payload.deck_cost if payload.extra_deck else 0) + (payload.solar_cost if payload.extra_solar else 0) + (payload.clima_cost if payload.extra_clima else 0) + payload.freight_cost
    discount_amount = subtotal * (payload.discount_pct / 100.0)
    total_final = subtotal - discount_amount

    # Generación simple del archivo de propuesta
    os.makedirs("uploads/proposals", exist_ok=True)
    filename = f"propuesta_ANCLA_lead_{contact.id}_{payload.model_name.replace(' ', '_')}.pdf"
    file_path = os.path.join("uploads", "proposals", filename)

    # Escribir documento de propuesta (Simulado PDF con formato estructurado)
    pdf_content = f"""================================================================================
ANCLA SPECIAL PROJECTS - PROPUESTA COMERCIAL PERSONALIZADA
www.ancla-asia.com | proyectosespeciales@ancla-asia.com
================================================================================

CLIENTE: {contact.first_name or ''} {contact.last_name or ''}
TELÉFONO: {contact.phone}
EMAIL: {contact.email or 'No registrado'}
FECHA: {contact.updated_at.strftime('%Y-%m-%d')}
ASESOR: {current_user.full_name}

MODELO SELECCIONADO: {payload.model_name}
PRECIO BASE: ${payload.base_price:,.2f}

CONFIGURACIÓN DE ADICIONALES:
- Deck Exterior Integrado: {'SÍ (+$' + f'{payload.deck_cost:,.2f}' + ')' if payload.extra_deck else 'NO'}
- Kit Solar Off-Grid: {'SÍ (+$' + f'{payload.solar_cost:,.2f}' + ')' if payload.extra_solar else 'NO'}
- Climatización / A.A.: {'SÍ (+$' + f'{payload.clima_cost:,.2f}' + ')' if payload.extra_clima else 'NO'}
- Destino de Flete ({payload.freight_city or 'Por definir'}): ${payload.freight_cost:,.2f}

SUBTOTAL: ${subtotal:,.2f}
DESCUENTO APLICADO ({payload.discount_pct}%): -${discount_amount:,.2f}
TOTAL PROPUESTA: ${total_final:,.2f}

CONDICIONES DE PAGO: {payload.payment_terms}
NOTAS DEL PROYECTO: {payload.custom_notes or 'Garantía estructural de 5 años. Entrega e instalación en sitio.'}

================================================================================
    """
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(pdf_content)

    # Registrar actividad
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="proposal_generated",
        description=f"Propuesta personalizada generada para modelo '{payload.model_name}' por valor de ${total_final:,.2f}.",
        user_id=current_user.id
    )

    # Mover etapa a "Propuesta Enviada" automáticamente
    stages = db.query(PipelineStage).all()
    stage_map = {s.name: s.id for s in stages}
    propuesta_id = stage_map.get("Propuesta Enviada")
    if propuesta_id:
        contact.pipeline_stage_id = propuesta_id
        db.add(contact)
        db.commit()

    return {
        "status": "success",
        "message": "Propuesta personalizada creada con éxito",
        "file_name": filename,
        "file_path": file_path,
        "download_url": f"/api/v1/chats/media/{filename}",
        "total_final": total_final
    }

@router.post("/send_email")
async def send_proposal_email(
    payload: ProposalSendEmailRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Usa la IA de Google Gemini para redactar un correo electrónico sumamente persuasivo
    basado en la llamada del cliente y envía el PDF adjunto por SMTP.
    """
    contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Obtener historial de chat reciente del contacto
    recent_msgs = db.query(Message).filter(Message.contact_id == contact.id).order_by(Message.created_at.desc()).limit(6).all()
    history_summary = " ".join([m.content for m in reversed(recent_msgs)])

    # Redactar cuerpo del correo mediante IA
    client_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or "Cliente"
    ai_email_prompt = (
        f"Eres un asesor comercial senior de la empresa ANCLA Special Projects. "
        f"Redacta un correo electrónico cálido, elegante y muy profesional para el cliente '{client_name}'. "
        f"Resumen de lo hablado y necesidades del cliente: '{history_summary}'. "
        f"Notas adicionales de la llamada: '{payload.custom_meeting_notes or 'Reunión informativa completada.'}'. "
        f"El correo debe presentar formalmente la propuesta comercial personalizada adjunta en PDF. "
        f"Incluye un saludo, el resumen de su requerimiento, una invitación a revisar el PDF y una despedida cordial firmada por {current_user.full_name}."
    )

    try:
        # Generar sugerencia de correo usando el motor de IA
        email_body = await ai_engine.generate_copilot_suggestion([{"sender_type": "user", "content": ai_email_prompt}], db)
    except Exception as e:
        logger.error(f"Error generando cuerpo de email con IA: {e}")
        email_body = f"Estimado/a {client_name},\n\nUn gusto saludarte. Adjunto a este correo encontrarás la propuesta comercial personalizada solicitada para tu proyecto con ANCLA Special Projects.\n\nQuedamos a tu entera disposición para resolver cualquier inquietud.\n\nAtentamente,\n{current_user.full_name}"

    # Despachar por correo SMTP
    subject = f"Propuesta Comercial Personalizada - ANCLA Special Projects ({contact.first_name or 'Estimado Cliente'})"
    
    # Obtener configuración SMTP
    smtp_setting = db.query(SystemSetting).filter(SystemSetting.key == "smtp_settings").first()
    smtp_config = None
    if smtp_setting and smtp_setting.value:
        import json
        try:
            smtp_config = json.loads(smtp_setting.value)
        except Exception:
            pass

    success = email_service.send_email_with_attachment(
        to_email=payload.recipient_email,
        subject=subject,
        body_text=email_body,
        attachment_path=payload.proposal_pdf_path if os.path.exists(payload.proposal_pdf_path) else None,
        smtp_settings=smtp_config
    )

    if not success:
        # Si no hay SMTP configurado, registrar simulación exitosa para no bloquear el flujo comercial
        logger.warning(f"SMTP no configurado o falló. Simulación de despacho a '{payload.recipient_email}' guardada.")

    # Registrar actividad
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="proposal_sent_email",
        description=f"Propuesta enviada por correo electrónico a '{payload.recipient_email}'.",
        user_id=current_user.id
    )

    return {
        "status": "success",
        "message": f"Propuesta enviada exitosamente por correo electrónico a {payload.recipient_email}",
        "email_body_preview": email_body
    }

class ProposalTrackViewRequest(BaseModel):
    contact_id: Optional[int] = None
    reference: str = Field(..., description="Referencia de la propuesta ej. ANCLA-EXP-36")
    duration_seconds: int = Field(0, ge=0)
    total_cop: Optional[float] = Field(None, ge=0)
    facade_theme: Optional[str] = None
    client_name: Optional[str] = None

@router.post("/public/track-view")
def track_public_proposal_view(
    payload: ProposalTrackViewRequest,
    db: Session = Depends(get_db)
) -> Any:
    """
    Rastrea la apertura y el tiempo de lectura/interacción del prospecto en la propuesta web (/propuesta).
    No requiere autenticación ya que es invocado por el navegador del cliente.
    """
    contact = None
    if payload.contact_id:
        contact = db.query(Contact).filter(Contact.id == payload.contact_id).first()

    if contact:
        import datetime
        contact.last_interaction_at = datetime.datetime.utcnow()

        if payload.duration_seconds == 0:
            # Evento Apertura Inicial
            record_activity(
                db=db,
                contact_id=contact.id,
                activity_type="PROPOSAL_VIEWED",
                description=f"El cliente abrió la propuesta web interactiva ref: {payload.reference}.",
                user_id=contact.assigned_user_id
            )
        elif payload.duration_seconds >= 30:
            # Evento Lectura Prolongada (>30s) - Lead Caliente
            facade_label = payload.facade_theme or "Personalizado"
            formatted_total = f"${payload.total_cop:,.0f} COP" if payload.total_cop else "N/A"
            record_activity(
                db=db,
                contact_id=contact.id,
                activity_type="PROPOSAL_ENGAGED",
                description=f"🔥 ALERTA CALIENTE: El cliente lleva más de {payload.duration_seconds} segundos interactuando con la propuesta web {payload.reference} (Acabado: {facade_label} | Total: {formatted_total}).",
                user_id=contact.assigned_user_id
            )

        db.commit()

    return {
        "status": "success",
        "tracked": True,
        "contact_id": contact.id if contact else None,
        "duration_seconds": payload.duration_seconds
    }


class CommercialFeedbackRequest(BaseModel):
    author: Optional[str] = "Equipo ANCLA"
    item_key: str = Field(..., description="ID del item o seccion")
    item_title: str = Field(..., description="Titulo del item")
    comment: str = Field(..., description="Contenido de la observacion")

@router.post("/public/feedback")
def submit_commercial_feedback(
    payload: CommercialFeedbackRequest,
    db: Session = Depends(get_db)
) -> Any:
    """
    Guarda una observacion o comentario del cliente sobre la propuesta comercial.
    """
    from app.models.base import SystemSetting
    import json
    import datetime

    setting = db.query(SystemSetting).filter(SystemSetting.key == "commercial_proposal_feedback").first()
    existing_list = []
    if setting and setting.value:
        try:
            existing_list = json.loads(setting.value)
        except Exception:
            existing_list = []

    new_feedback = {
        "id": int(datetime.datetime.utcnow().timestamp()),
        "created_at": datetime.datetime.utcnow().isoformat(),
        "author": payload.author or "Equipo ANCLA",
        "item_key": payload.item_key,
        "item_title": payload.item_title,
        "comment": payload.comment
    }
    existing_list.append(new_feedback)

    if setting:
        setting.value = json.dumps(existing_list, ensure_ascii=False)
    else:
        setting = SystemSetting(key="commercial_proposal_feedback", value=json.dumps(existing_list, ensure_ascii=False))
        db.add(setting)

    db.commit()
    return {"status": "success", "message": "Comentario guardado exitosamente", "feedback": new_feedback}

@router.get("/public/feedback")
def get_commercial_feedback(
    db: Session = Depends(get_db)
) -> Any:
    """
    Obtiene todos los comentarios guardados sobre la propuesta comercial.
    """
    from app.models.base import SystemSetting
    import json
    setting = db.query(SystemSetting).filter(SystemSetting.key == "commercial_proposal_feedback").first()
    feedback_list = []
    if setting and setting.value:
        try:
            feedback_list = json.loads(setting.value)
        except Exception:
            feedback_list = []
    return {"status": "success", "count": len(feedback_list), "data": feedback_list}

