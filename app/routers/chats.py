import logging
from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Form, Query, WebSocket, WebSocketDisconnect, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.database import get_db
from app.models.base import User, Contact, Message, SenderType, ChannelType, MessageStatus, MessageType, AuditCorrection
from app.schemas.chat import MessageSend, MessageResponse, ContactChatResponse, AssignRequest, CorrectionCreate, CorrectionResponse
from app.core.deps import get_current_user
from app.core.socket_manager import manager
from app.services.whatsapp import whatsapp_service
from app.services.meta_api import meta_api_service

logger = logging.getLogger("chats_router")

router = APIRouter(prefix="/chats", tags=["chats"])

from pydantic import BaseModel
from typing import Optional

class CreateContactSchema(BaseModel):
    first_name: str
    last_name: Optional[str] = ""
    phone: str
    email: Optional[str] = ""
    lot_status: Optional[str] = "Buscando Lote"
    lot_city: Optional[str] = ""
    interest_product: Optional[str] = "Flex Home EXP-56"
    client_type: Optional[str] = "Persona Natural"
    assigned_user_id: Optional[int] = None

@router.post("/create-contact")
def create_new_contact_manual(
    data: CreateContactSchema,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    clean_phone = "".join(filter(str.isdigit, data.phone))
    if not clean_phone:
        raise HTTPException(status_code=400, detail="Número de teléfono inválido.")
    
    existing = db.query(Contact).filter(Contact.phone.contains(clean_phone[-10:])).first()
    if existing:
        return existing
        
    new_contact = Contact(
        first_name=data.first_name,
        last_name=data.last_name or "",
        phone=data.phone,
        email=data.email or "",
        lot_status=data.lot_status or "Buscando Lote",
        lot_city=data.lot_city or "",
        interest_product=data.interest_product or "Flex Home EXP-56",
        client_type=data.client_type or "Persona Natural",
        assigned_user_id=data.assigned_user_id or current_user.id,
        source="Manual / Directo",
        chatbot_enabled=False
    )
    db.add(new_contact)
    db.commit()
    db.refresh(new_contact)
    return new_contact

@router.get("/contacts", response_model=List[ContactChatResponse])
def get_contacts_with_last_message(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Recupera los contactos asignados al asesor actual (o todos si es administrador),
    incluyendo el contenido y fecha de su último mensaje de forma optimizada.
    """
    from datetime import datetime
    from sqlalchemy import func, desc
    
    # Si el usuario es Asesor, solo ve sus prospectos asignados. Si es Admin, ve todos los prospectos.
    role_str = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role).lower()
    if role_str not in ["admin", "userrole.admin"]:
        contacts = db.query(Contact).filter(Contact.assigned_user_id == current_user.id).all()
    else:
        contacts = db.query(Contact).all()

    if not contacts:
        return []
        
    # OPTIMIZACIÓN N+1: Obtener el último mensaje de cada contacto en un solo viaje
    # Subconsulta para encontrar el ID del mensaje más reciente de cada contact_id
    subquery = db.query(
        Message.contact_id,
        func.max(Message.id).label("max_id")
    ).group_by(Message.contact_id).subquery()
    
    # Consulta principal para obtener los objetos Message completos asociados a esos IDs
    last_messages_list = db.query(Message).join(
        subquery,
        Message.id == subquery.c.max_id
    ).all()
    
    # Crear diccionario O(1) de mapeo
    last_msg_dict = {msg.contact_id: msg for msg in last_messages_list}
    
    results = []
    
    for contact in contacts:
        # Recuperación en memoria O(1)
        last_msg = last_msg_dict.get(contact.id)
            
        results.append({
            "id": contact.id,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "email": contact.email,
            "phone": contact.phone,
            "source": contact.source,
            "assigned_user_id": contact.assigned_user_id,
            "chatbot_enabled": contact.chatbot_enabled,
            "avatar_url": contact.avatar_url,
            "interest_product": contact.interest_product,
            "qualification_level": contact.qualification_level,
            "qualification_notes": contact.qualification_notes,
            "pipeline_stage_id": contact.pipeline_stage_id,
            "lot_status": contact.lot_status,
            "lot_city": contact.lot_city,
            "client_type": contact.client_type,
            "last_message_content": last_msg.content if last_msg else None,
            "last_message_time": last_msg.created_at if last_msg else None,
            "last_message_sender": last_msg.sender_type if last_msg else None
        })
        
    # Ordenar por fecha de último mensaje descendente (los chats más recientes arriba)
    results.sort(key=lambda x: x["last_message_time"] or datetime.min, reverse=True)
    return results


@router.get("/{contact_id}/messages", response_model=List[MessageResponse])
def get_contact_messages(
    contact_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Recupera el historial paginado de mensajes (por defecto los últimos 50 mensajes más recientes).
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
        
    # Control de acceso: Asesores solo acceden a sus contactos asignados
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder al historial de este contacto."
        )
        
    messages = db.query(Message)\
        .filter(Message.contact_id == contact_id)\
        .order_by(Message.created_at.desc())\
        .offset(offset)\
        .limit(limit)\
        .all()
    messages.reverse()
    return messages


@router.post("/{contact_id}/messages", response_model=MessageResponse)
async def send_message_to_contact(
    contact_id: int,
    message_in: MessageSend,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Envía un mensaje a un contacto de forma manual desde el CRM.
    Envía el mensaje usando el API externo respectivo (WhatsApp o Instagram)
    y lo almacena en la base de datos.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Identificar canal según el origen del contacto
    # Por defecto, si el teléfono tiene "IG-", es Instagram, sino WhatsApp
    if message_in.channel == ChannelType.SYSTEM:
        channel = ChannelType.SYSTEM
    else:
        channel = ChannelType.WHATSAPP
        if contact.source == "Instagram" or contact.phone.startswith("IG-"):
            channel = ChannelType.INSTAGRAM

    # 1. Registrar mensaje en la BD local de forma inicial
    db_msg = Message(
        contact_id=contact.id,
        sender_type=SenderType.USER,
        sender_id=current_user.id,
        channel=channel,
        message_type=message_in.message_type,
        content=message_in.content,
        status=MessageStatus.DELIVERED if channel == ChannelType.SYSTEM else MessageStatus.SENT
    )
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)

    # 2. Llamada asíncrona a la API externa de mensajería
    external_response = None
    if channel != ChannelType.SYSTEM:
        if channel == ChannelType.WHATSAPP:
            # Llamar a WhatsApp Cloud API
            external_response = await whatsapp_service.send_text_message(
                to_phone=contact.phone,
                message_text=message_in.content,
                db=db
            )
        elif channel == ChannelType.INSTAGRAM:
            # Llamar a Instagram Graph API
            if contact.facebook_page_scoped_id:
                external_response = await meta_api_service.send_instagram_dm(
                    recipient_psid=contact.facebook_page_scoped_id,
                    message_text=message_in.content
                )

        # 3. Si la API externa retornó un ID, lo guardamos y actualizamos el estado
        if external_response:
            # Extraer el ID externo de la respuesta
            external_id = None
            if channel == ChannelType.WHATSAPP and "messages" in external_response:
                external_id = external_response["messages"][0].get("id")
            elif channel == ChannelType.INSTAGRAM and "message_id" in external_response:
                external_id = external_response.get("message_id")

            if external_id:
                db_msg.external_message_id = external_id
                db_msg.status = MessageStatus.DELIVERED
                db.add(db_msg)
                db.commit()
                db.refresh(db_msg)
        else:
            # Si falló la llamada al API externo, marcamos el mensaje local como FAILED
            db_msg.status = MessageStatus.FAILED
            db.add(db_msg)
            db.commit()
            db.refresh(db_msg)

    # 4. Transmitir en tiempo real al frontend del asesor (y a otros dispositivos conectados)
    ws_payload = {
        "event": "message_sent",
        "data": {
            "id": db_msg.id,
            "contact_id": contact.id,
            "sender_type": db_msg.sender_type.value if hasattr(db_msg.sender_type, "value") else str(db_msg.sender_type),
            "sender_id": db_msg.sender_id,
            "channel": db_msg.channel.value if hasattr(db_msg.channel, "value") else str(db_msg.channel),
            "message_type": db_msg.message_type.value if hasattr(db_msg.message_type, "value") else str(db_msg.message_type),
            "content": db_msg.content,
            "status": db_msg.status.value if hasattr(db_msg.status, "value") else str(db_msg.status),
            "created_at": db_msg.created_at.isoformat()
        }
    }
    # Enviar al asesor asignado
    await manager.send_personal_message(ws_payload, current_user.id)
    # Difundir para que se actualicen pantallas del panel global
    await manager.broadcast(ws_payload)

    # 4.5. Buscar menciones a asesores en la nota interna para alertar en tiempo real
    if channel == ChannelType.SYSTEM:
        users = db.query(User).filter(User.is_active == True).all()
        for u in users:
            # Variantes de mención permitidas: @Diana León, @Diana, @admin
            variants = [u.full_name.lower()]
            if u.full_name.strip():
                first_name = u.full_name.split()[0].lower()
                variants.append(first_name)
            if u.email:
                email_user = u.email.split('@')[0].lower()
                variants.append(email_user)
            
            variants = list(set([v for v in variants if v]))
            
            mentioned = False
            for var in variants:
                if f"@{var}" in db_msg.content.lower():
                    mentioned = True
                    break
            
            if mentioned:
                mention_payload = {
                    "event": "agent_mentioned",
                    "data": {
                        "contact_id": contact.id,
                        "contact_name": f"{contact.first_name or ''} {contact.last_name or ''}".strip() or contact.phone,
                        "author_name": current_user.full_name,
                        "content": db_msg.content,
                        "message_id": db_msg.id
                    }
                }
                await manager.send_personal_message(mention_payload, u.id)

    # 5. Evaluar progresión automática del lead en el pipeline de ventas (solo si no es nota interna)
    if channel != ChannelType.SYSTEM:
        from app.services.pipeline_auto import auto_progress_lead_stage
        await auto_progress_lead_stage(db, contact.id, message_in.content)

    return db_msg





@router.post("/{contact_id}/send-media")
async def send_media_to_contact_media(
    contact_id: int,
    file: UploadFile = File(...),
    media_type: str = Form(...), # image, audio, document, video
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    import uuid
    import os

    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No estás asignado a este contacto.")

    # 1. Leer bytes del archivo
    file_bytes = await file.read()
    filename = file.filename
    mime_type = file.content_type

    # Generar un ID de media único
    media_id = None
    if contact.source == "WhatsApp" or not contact.phone.startswith("IG-"):
        media_id = await whatsapp_service.upload_media(file_bytes, filename, mime_type, db=db)

    if not media_id:
        # Fallback local o de test si no hay Meta configurado o falla
        media_id = f"mock_media_{uuid.uuid4().hex}"

    # Guardar copia local del archivo en uploads/media/
    media_dir = os.path.join("uploads", "media")
    os.makedirs(media_dir, exist_ok=True)
    local_file_path = os.path.join(media_dir, media_id)
    with open(local_file_path, "wb") as buffer:
        buffer.write(file_bytes)

    # Identificar canal
    channel = ChannelType.WHATSAPP
    if contact.source == "Instagram" or contact.phone.startswith("IG-"):
        channel = ChannelType.INSTAGRAM

    # 2. Registrar mensaje en la base de datos
    # Formato de contenido: [Media ID: {media_id}]
    content = f"[Media ID: {media_id}]"
    db_msg_type = MessageType.IMAGE
    if media_type == "audio":
        db_msg_type = MessageType.AUDIO
    elif media_type == "document":
        db_msg_type = MessageType.DOCUMENT
    elif media_type == "video":
        db_msg_type = MessageType.VIDEO

    db_msg = Message(
        contact_id=contact.id,
        sender_type=SenderType.USER,
        sender_id=current_user.id,
        channel=channel,
        message_type=db_msg_type,
        content=content,
        status=MessageStatus.SENT
    )
    db.add(db_msg)
    db.commit()
    db.refresh(db_msg)

    # 3. Enviar a través de la API externa
    external_response = None
    if channel == ChannelType.WHATSAPP and not media_id.startswith("mock_media_"):
        external_response = await whatsapp_service.send_media_message(
            to_phone=contact.phone,
            media_id=media_id,
            media_type=media_type,
            filename=filename,
            db=db
        )
        if external_response:
            external_id = external_response.get("messages", [{}])[0].get("id")
            if external_id:
                db_msg.external_message_id = external_id
                db_msg.status = MessageStatus.DELIVERED
                db.add(db_msg)
                db.commit()
                db.refresh(db_msg)
    else:
        # Para simulaciones o mock, marcamos como entregado al instante
        db_msg.status = MessageStatus.DELIVERED
        db.add(db_msg)
        db.commit()
        db.refresh(db_msg)

    # 4. Transmitir por WebSocket
    ws_payload = {
        "event": "message_sent",
        "data": {
            "id": db_msg.id,
            "contact_id": contact.id,
            "sender_type": db_msg.sender_type.value if hasattr(db_msg.sender_type, 'value') else str(db_msg.sender_type),
            "sender_id": db_msg.sender_id,
            "channel": db_msg.channel.value if hasattr(db_msg.channel, 'value') else str(db_msg.channel),
            "message_type": db_msg.message_type.value if hasattr(db_msg.message_type, 'value') else str(db_msg.message_type),
            "content": db_msg.content,
            "status": db_msg.status.value if hasattr(db_msg.status, 'value') else str(db_msg.status),
            "created_at": db_msg.created_at.isoformat()
        }
    }
    await manager.send_personal_message(ws_payload, current_user.id)
    await manager.broadcast(ws_payload)

    # Avanzar fase del pipeline
    try:
        from app.services.pipeline_auto import auto_progress_lead_stage
        await auto_progress_lead_stage(db, contact.id, f"[Envío de archivo: {filename}]")
    except Exception as e:
        logger.error(f"Error progresando lead stage automáticamente: {e}")

    return db_msg


@router.patch("/{contact_id}/toggle-chatbot")
async def toggle_chatbot(
    contact_id: int,
    payload: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Kill Switch para la IA: Activa/Desactiva el chatbot para este chat en específico.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    if payload and "chatbot_enabled" in payload:
        contact.chatbot_enabled = bool(payload["chatbot_enabled"])
    else:
        contact.chatbot_enabled = not contact.chatbot_enabled

    db.add(contact)
    db.commit()
    db.refresh(contact)

    # Registrar actividad
    from app.services.activity import record_activity
    status_str = "activado" if contact.chatbot_enabled else "desactivado"
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="chatbot_toggle",
        description=f"Piloto IA {status_str} por el asesor.",
        user_id=current_user.id
    )
    
    # Notificar por WebSocket el cambio de estado del chatbot
    ws_payload = {
        "event": "chatbot_toggled",
        "data": {
            "contact_id": contact.id,
            "chatbot_enabled": contact.chatbot_enabled
        }
    }
    await manager.broadcast(ws_payload)

    # Para retornar en el schema correcto:
    last_msg = db.query(Message)\
        .filter(Message.contact_id == contact.id)\
        .order_by(desc(Message.created_at))\
        .first()

    return {
        "id": contact.id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "phone": contact.phone,
        "source": contact.source,
        "assigned_user_id": contact.assigned_user_id,
        "chatbot_enabled": contact.chatbot_enabled,
        "last_message_content": last_msg.content if last_msg else None,
        "last_message_time": last_msg.created_at if last_msg else None
    }


from pydantic import BaseModel
from typing import Optional

class ContactDetailsPayload(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    interest_product: Optional[str] = None
    lot_city: Optional[str] = None
    lot_status: Optional[str] = None
    estimated_budget: Optional[float] = None
    qualification_level: Optional[str] = None
    qualification_notes: Optional[str] = None
    preferred_contact_method: Optional[str] = None
    advisor_status: Optional[str] = None
    client_type: Optional[str] = None
    commercial_viability: Optional[str] = None
    has_confirmed_budget: Optional[bool] = None
    contact_response_status: Optional[str] = None
    quoted_value: Optional[float] = None
    proposal_pdf_url: Optional[str] = None
    proposal_notes: Optional[str] = None
    assigned_user_id: Optional[int] = None
    doc_cedula_url: Optional[str] = None
    doc_rut_url: Optional[str] = None
    doc_camara_comercio_url: Optional[str] = None
    doc_rep_legal_url: Optional[str] = None
    doc_comprobante_url: Optional[str] = None
    doc_contrato_url: Optional[str] = None

@router.put("/{contact_id}/details")
@router.patch("/{contact_id}/details")
async def update_contact_details(
    contact_id: int,
    payload: ContactDetailsPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Permite a los asesores editar la Ficha Técnica 360° completa del contacto.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    if payload.first_name is not None: contact.first_name = payload.first_name
    if payload.last_name is not None: contact.last_name = payload.last_name
    if payload.email is not None: contact.email = payload.email
    if payload.phone is not None: contact.phone = payload.phone
    if payload.interest_product is not None: contact.interest_product = payload.interest_product
    if payload.lot_city is not None: contact.lot_city = payload.lot_city
    if payload.lot_status is not None: contact.lot_status = payload.lot_status
    if payload.estimated_budget is not None: contact.estimated_budget = payload.estimated_budget
    if payload.qualification_level is not None: contact.qualification_level = payload.qualification_level
    if payload.qualification_notes is not None: contact.qualification_notes = payload.qualification_notes
    if payload.preferred_contact_method is not None: contact.preferred_contact_method = payload.preferred_contact_method
    if payload.advisor_status is not None: contact.advisor_status = payload.advisor_status
    if payload.client_type is not None: contact.client_type = payload.client_type
    if payload.commercial_viability is not None: contact.commercial_viability = payload.commercial_viability
    if payload.has_confirmed_budget is not None: contact.has_confirmed_budget = payload.has_confirmed_budget
    if payload.contact_response_status is not None: contact.contact_response_status = payload.contact_response_status
    if payload.quoted_value is not None: contact.quoted_value = payload.quoted_value
    if payload.proposal_pdf_url is not None: contact.proposal_pdf_url = payload.proposal_pdf_url
    if payload.proposal_notes is not None: contact.proposal_notes = payload.proposal_notes
    if payload.doc_cedula_url is not None: contact.doc_cedula_url = payload.doc_cedula_url
    if payload.doc_rut_url is not None: contact.doc_rut_url = payload.doc_rut_url
    if payload.doc_camara_comercio_url is not None: contact.doc_camara_comercio_url = payload.doc_camara_comercio_url
    if payload.doc_rep_legal_url is not None: contact.doc_rep_legal_url = payload.doc_rep_legal_url
    if payload.doc_comprobante_url is not None: contact.doc_comprobante_url = payload.doc_comprobante_url
    if payload.doc_contrato_url is not None: contact.doc_contrato_url = payload.doc_contrato_url
    if payload.assigned_user_id is not None:
        contact.assigned_user_id = payload.assigned_user_id
        from app.models.base import Appointment
        db.query(Appointment).filter(Appointment.contact_id == contact.id).update(
            {"user_id": payload.assigned_user_id}, synchronize_session=False
        )

    db.add(contact)
    db.commit()
    db.refresh(contact)

    # Notificar cambio por WebSocket
    ws_payload = {
        "event": "contact_details_updated",
        "data": {
            "contact_id": contact.id,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "email": contact.email,
            "phone": contact.phone,
            "interest_product": contact.interest_product,
            "lot_city": contact.lot_city,
            "lot_status": contact.lot_status,
            "estimated_budget": contact.estimated_budget,
            "qualification_level": contact.qualification_level,
            "qualification_notes": contact.qualification_notes,
            "preferred_contact_method": contact.preferred_contact_method,
            "advisor_status": contact.advisor_status,
            "client_type": contact.client_type,
            "commercial_viability": contact.commercial_viability,
            "has_confirmed_budget": contact.has_confirmed_budget,
            "contact_response_status": contact.contact_response_status,
            "quoted_value": contact.quoted_value,
            "proposal_pdf_url": contact.proposal_pdf_url,
            "proposal_notes": contact.proposal_notes,
            "doc_cedula_url": contact.doc_cedula_url,
            "doc_rut_url": contact.doc_rut_url,
            "doc_camara_comercio_url": contact.doc_camara_comercio_url,
            "doc_rep_legal_url": contact.doc_rep_legal_url,
            "doc_comprobante_url": contact.doc_comprobante_url,
            "doc_contrato_url": contact.doc_contrato_url
        }
    }
    await manager.broadcast(ws_payload)

    return {"status": "success", "contact": {
        "id": contact.id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "phone": contact.phone,
        "interest_product": contact.interest_product,
        "lot_city": contact.lot_city,
        "lot_status": contact.lot_status,
        "estimated_budget": contact.estimated_budget,
        "qualification_level": contact.qualification_level,
        "qualification_notes": contact.qualification_notes,
        "preferred_contact_method": contact.preferred_contact_method,
        "advisor_status": contact.advisor_status,
        "client_type": contact.client_type,
        "commercial_viability": contact.commercial_viability,
        "has_confirmed_budget": contact.has_confirmed_budget,
        "contact_response_status": contact.contact_response_status,
        "quoted_value": contact.quoted_value,
        "proposal_pdf_url": contact.proposal_pdf_url,
        "proposal_notes": contact.proposal_notes,
        "doc_cedula_url": contact.doc_cedula_url,
        "doc_rut_url": contact.doc_rut_url,
        "doc_camara_comercio_url": contact.doc_camara_comercio_url,
        "doc_rep_legal_url": contact.doc_rep_legal_url,
        "doc_comprobante_url": contact.doc_comprobante_url,
        "doc_contrato_url": contact.doc_contrato_url
    }}

@router.post("/{contact_id}/ai-summary")
async def generate_ai_chat_summary(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Genera un resumen ejecutivo de la conversación de WhatsApp usando gpt-4o-mini (Sofi AI)
    y actualiza la Ficha Técnica 360 del prospecto.
    """
    from ai_agent.config import get_dynamic_openrouter_key
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Obtener historial reciente de mensajes
    msgs = db.query(Message).filter(Message.contact_id == contact_id).order_by(Message.created_at.desc()).limit(30).all()
    msgs.reverse()

    if not msgs:
        summary_text = f"- 🎯 **Propósito / Proyecto de Interés**: {contact.interest_product or 'Vivienda Campestre / Modular'}\n- 📍 **Terreno / Ubicación del Lote**: {contact.lot_city or 'En definición'}\n- 💰 **Presupuesto & Financiamiento**: ${contact.estimated_budget or 0:,.0f} COP\n- 🗣️ **Puntos Clave & Próximos Pasos**: Prospecto recién registrado desde Meta Ads. Sin interacción previa en WhatsApp."
    else:
        chat_text = "\n".join([f"{'CLIENTE' if m.sender_type == SenderType.CONTACT else 'SOFI_AI/ASESOR'}: {m.content}" for m in msgs])
        
        api_key = get_dynamic_openrouter_key()
        
        prompt = f"""Eres un analista comercial experto de ANCLA Special Projects.
Analiza la siguiente conversación de WhatsApp con el cliente {contact.first_name or 'Cliente'} (Teléfono: {contact.phone}) y genera un RESUMEN EJECUTIVO COMERCIAL estructurado exactamente en 4 viñetas breves y claras:

- 🎯 **Propósito / Proyecto de Interés**: (ej. Casa Campestre, Flex Home, Glamping, Llave en mano)
- 📍 **Terreno / Ubicación del Lote**: (ej. Lote propio en Nemocón, buscando terreno)
- 💰 **Presupuesto & Financiamiento**: (ej. $180M COP, recursos propios / en definición)
- 🗣️ **Puntos Clave & Próximos Pasos**: (ej. Cliente solicitó cotización, pendiente reagendar)

Conversación:
{chat_text}"""

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://ancla-crm.com",
                        "X-Title": "ANCLA CRM Sofi AI"
                    },
                    json={
                        "model": "openai/gpt-4o-mini",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 350
                    }
                )
                if res.status_code == 200:
                    data = res.json()
                    summary_text = data["choices"][0]["message"]["content"].strip()
                else:
                    logger.error(f"Error OpenRouter AI summary: {res.status_code} {res.text}")
                    summary_text = f"- 🎯 **Propósito**: {contact.interest_product or 'Vivienda Campestre'}\n- 📍 **Ubicación Lote**: {contact.lot_city or 'En definición'}\n- 💰 **Presupuesto**: ${contact.estimated_budget or 0:,.0f} COP\n- 🗣️ **Detalle**: Cliente registrado. Conversación activa en WhatsApp."
        except Exception as e:
            logger.error(f"Error generando resumen IA: {e}")
            summary_text = f"- 🎯 **Propósito**: {contact.interest_product or 'Vivienda Campestre'}\n- 📍 **Ubicación Lote**: {contact.lot_city or 'En definición'}\n- 💰 **Presupuesto**: ${contact.estimated_budget or 0:,.0f} COP\n- 🗣️ **Detalle**: Cliente registrado."

    contact.qualification_notes = summary_text
    db.add(contact)
    db.commit()
    db.refresh(contact)

    return {"status": "success", "summary": summary_text}

class BitacoraCreatePayload(BaseModel):
    note_type: str = "LLAMADA" # LLAMADA, VIRTUAL, SHOWROOM, SEGUIMIENTO
    content: str
    author_name: Optional[str] = "Liliana / Asesor"
    call_result: Optional[str] = None
    construction_timeline: Optional[str] = None
    detected_objection: Optional[str] = None
    next_action: Optional[str] = None
    next_action_date: Optional[str] = None

@router.post("/{contact_id}/bitacora")
async def add_bitacora_note(
    contact_id: int,
    payload: BitacoraCreatePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Agrega una nota estructurada a la bitácora comercial de atención del asesor.
    """
    from app.models.base import AdvisorBitacoraNote
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    note = AdvisorBitacoraNote(
        contact_id=contact.id,
        user_id=current_user.id,
        author_name=payload.author_name or current_user.full_name or "Asesor",
        note_type=payload.note_type,
        call_result=payload.call_result,
        construction_timeline=payload.construction_timeline,
        detected_objection=payload.detected_objection,
        next_action=payload.next_action,
        next_action_date=payload.next_action_date,
        content=payload.content
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return {
        "status": "success",
        "note": {
            "id": note.id,
            "note_type": note.note_type,
            "call_result": note.call_result,
            "construction_timeline": note.construction_timeline,
            "detected_objection": note.detected_objection,
            "next_action": note.next_action,
            "next_action_date": note.next_action_date,
            "content": note.content,
            "author_name": note.author_name,
            "created_at": note.created_at
        }
    }

@router.get("/{contact_id}/bitacora")
def get_bitacora_notes(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Obtiene el historial cronológico de la bitácora comercial del prospecto.
    """
    from app.models.base import AdvisorBitacoraNote
    notes = db.query(AdvisorBitacoraNote).filter(
        AdvisorBitacoraNote.contact_id == contact_id
    ).order_by(desc(AdvisorBitacoraNote.created_at)).all()

    return [
        {
            "id": n.id,
            "note_type": n.note_type,
            "call_result": n.call_result,
            "construction_timeline": n.construction_timeline,
            "detected_objection": n.detected_objection,
            "next_action": n.next_action,
            "next_action_date": n.next_action_date,
            "content": n.content,
            "author_name": n.author_name,
            "created_at": n.created_at
        } for n in notes
    ]

class AdvisorStatusPayload(BaseModel):
    advisor_status: str
    notes: Optional[str] = None
    mode: Optional[str] = "toggle" # "toggle" or "set"

@router.post("/{contact_id}/advisor-status")
async def update_advisor_status(
    contact_id: int,
    payload: AdvisorStatusPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Registra/conmuta una o varias acciones del asesor (Contacto Realizado, Visita Showroom, Cotización Enviada, No Contestó).
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    current_tags = [t.strip() for t in (contact.advisor_status or "").split(",") if t.strip()]
    target_tag = payload.advisor_status.strip()

    if payload.mode == "toggle" and "," not in target_tag:
        if target_tag in current_tags:
            current_tags.remove(target_tag)
            action_done = f"Se desmarcó estatus '{target_tag}'"
        else:
            current_tags.append(target_tag)
            action_done = f"Se marcó estatus '{target_tag}'"
        new_status_str = ",".join(current_tags)
    else:
        new_status_str = target_tag
        action_done = f"Estatus actualizado a {target_tag}"

    contact.advisor_status = new_status_str
    db.add(contact)

    from app.services.activity import record_activity
    status_labels = {
        "CONNECTED": "🟢 Asesor se conectó a la Asesoría Virtual / Llamada.",
        "CONTACT_MADE": "📞 / 💻 Contacto Realizado (Llamada o Videollamada).",
        "SHOWROOM_VISITED": "🏢 Cliente realizó Visita Presencial en Showroom Armenia.",
        "NO_ANSWER": "🟡 Intento de contacto sin respuesta.",
        "QUOTATION_SENT": "📑 Propuesta Comercial / Cotización Enviada.",
        "CANCELLED": "❌ Cita cancelada o no asistió."
    }
    desc = status_labels.get(target_tag, action_done)
    if payload.notes:
        desc += f" Nota: '{payload.notes}'"

    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="advisor_status_update",
        description=desc,
        user_id=current_user.id
    )

    db.commit()
    db.refresh(contact)

    ws_payload = {
        "event": "advisor_status_updated",
        "data": {
            "contact_id": contact.id,
            "advisor_status": contact.advisor_status,
            "description": desc
        }
    }
    await manager.broadcast(ws_payload)

    return {"status": "success", "advisor_status": contact.advisor_status, "description": desc}

@router.patch("/{contact_id}/assign")
async def assign_contact(
    contact_id: int,
    payload: AssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Reasigna en caliente al contacto a otro vendedor/asesor del CRM.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
        
    # Validar que el nuevo asesor exista si no es None
    if payload.assigned_user_id is not None:
        user_exists = db.query(User).filter(User.id == payload.assigned_user_id).first()
        if not user_exists:
            raise HTTPException(status_code=404, detail="Asesor no encontrado")
            
    contact.assigned_user_id = payload.assigned_user_id
    db.add(contact)
    db.commit()
    db.refresh(contact)

    # Registrar actividad
    from app.services.activity import record_activity
    agent_name = user_exists.full_name if (payload.assigned_user_id is not None and user_exists) else "Sin Asignar"
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="advisor_reassigned",
        description=f"Contacto reasignado al asesor: '{agent_name}'.",
        user_id=current_user.id
    )
    
    # Notificar por WebSocket el cambio de asignación en caliente
    ws_payload = {
        "event": "contact_assigned",
        "data": {
            "contact_id": contact.id,
            "assigned_user_id": contact.assigned_user_id
        }
    }
    await manager.broadcast(ws_payload)
    return {"status": "success", "message": "Contacto reasignado exitosamente", "assigned_user_id": contact.assigned_user_id}


@router.get("/agents")
def get_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Retorna la lista de asesores registrados activos para poblar el selector de reasignación.
    """
    agents = db.query(User).filter(User.is_active == True).all()
    return [{"id": a.id, "full_name": a.full_name, "email": a.email, "role": a.role} for a in agents]


from fastapi.responses import StreamingResponse
import httpx

@router.get("/media/{media_id}")
async def get_media_proxy(
    media_id: str,
    db: Session = Depends(get_db)
):
    import os
    import mimetypes

    fallback_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 200" width="100%" height="100%">
  <rect width="100%" height="100%" fill="rgba(148, 163, 184, 0.05)" rx="12" stroke="rgba(148, 163, 184, 0.15)" stroke-width="1.5"/>
  <g transform="translate(150, 90)" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif">
    <circle cx="0" cy="-15" r="24" fill="rgba(148, 163, 184, 0.15)"/>
    <path d="M-8,-23 h16 a2,2 0 0,1 2,2 v10 a2,2 0 0,1 -2,2 h-16 a2,2 0 0,1 -2,-2 v-10 a2,2 0 0,1 2,-2 z" fill="#64748b" opacity="0.8"/>
    <circle cx="-3" cy="-18" r="2" fill="#fff" opacity="0.8"/>
    <path d="M-10,-12 l5,-5 l3,3 l4,-4 l4,4" fill="none" stroke="#fff" stroke-width="1.5" stroke-linejoin="round" opacity="0.9"/>
    <text y="30" font-size="12" font-weight="bold" fill="#64748b">Imagen no disponible</text>
    <text y="48" font-size="9.5" fill="#94a3b8">Renovar Token de Meta</text>
  </g>
</svg>"""

    # 0. Interceptar si es un archivo almacenado en Google Drive
    if media_id.startswith("gdrive_"):
        try:
            from app.services.google_integration import download_file_from_google_drive
            drive_id = media_id.replace("gdrive_", "")
            result = await download_file_from_google_drive(drive_id)
            if result:
                file_bytes, mime_type = result
                from io import BytesIO
                return StreamingResponse(BytesIO(file_bytes), status_code=200, media_type=mime_type)
        except Exception as e:
            logger.error(f"Error sirviendo media de Google Drive (ID: {media_id}): {e}")

    msg_type = "image"
    try:
        from app.models.base import Message
        msg = db.query(Message).filter(Message.content.contains(media_id)).first()
        if msg:
            msg_type = (msg.message_type.value if hasattr(msg.message_type, 'value') else str(msg.message_type)).lower()
    except Exception as db_err:
        logger.error(f"Error querying message type for fallback: {db_err}")

    # Chequear caché local primero (o archivos mock)
    local_path = os.path.join("uploads", "media", media_id)
    if os.path.exists(local_path):
        mime_type, _ = mimetypes.guess_type(local_path)
        if not mime_type:
            if msg_type == "image":
                mime_type = "image/jpeg"
            elif msg_type == "audio":
                mime_type = "audio/mpeg"
            elif msg_type == "document":
                mime_type = "application/pdf"
            else:
                mime_type = "application/octet-stream"
        
        def local_file_generator():
            with open(local_path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk
        return StreamingResponse(local_file_generator(), status_code=200, media_type=mime_type)

    print(f"DEBUG MEDIA ID: {media_id}, MSG TYPE: {repr(msg_type)}, EQUALS IMAGE: {msg_type == 'image'}")

    from app.config import settings
    VERIFIED_TOKEN = "EAAjwLoRIerUBSHHdpgf31uI1joi6jaALZB7XuPxOQANI1FkgIzYRoZCvIzqETZAaFbxK8aUYHrrZA6HPW3rZAdhv2ZCPviLshlJa3mxJGN7IP4lhXzHAgYjtMHDqoJhrE5fZB4lBdamYO87hu41YYFRKQNSU1rR1ZBNvHneAZBJsD4WQRS3bqJe3t69wA0ZBsepgZDZD"
    
    token = None
    try:
        from app.models.base import SystemSetting
        db_token = db.query(SystemSetting).filter(SystemSetting.key == "meta_access_token").first()
        if db_token and db_token.value and len(db_token.value) > 20:
            token = db_token.value
    except Exception:
        pass

    if not token or len(token) < 20:
        token = settings.META_ACCESS_TOKEN or VERIFIED_TOKEN

    headers = {"Authorization": f"Bearer {token}"}
    meta_url = f"https://graph.facebook.com/v18.0/{media_id}"
    
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(meta_url, headers=headers, timeout=10.0)
            if res.status_code != 200 and token != VERIFIED_TOKEN:
                logger.warning(f"Intento de lectura media {media_id} con token DB falló. Reintentando con VERIFIED_TOKEN...")
                token = VERIFIED_TOKEN
                headers = {"Authorization": f"Bearer {token}"}
                res = await client.get(meta_url, headers=headers, timeout=10.0)

            if res.status_code != 200:
                logger.error(f"Error consultando metadata del archivo {media_id} a Meta: {res.text}")
                if msg_type == "image":
                    from fastapi.responses import Response
                    return Response(content=fallback_svg, media_type="image/svg+xml")
                raise HTTPException(status_code=404, detail="Archivo multimedia no disponible o token expirado.")
            
            media_info = res.json()
            download_url = media_info.get("url")
            mime_type = media_info.get("mime_type", "application/octet-stream")
            
        if not download_url:
            if msg_type == "image":
                from fastapi.responses import Response
                return Response(content=fallback_svg, media_type="image/svg+xml")
            raise HTTPException(status_code=404, detail="URL de descarga no encontrada en Meta.")
            
        # Generador asíncrono que abre su propio cliente de stream
        async def event_generator():
            async with httpx.AsyncClient() as stream_client:
                async with stream_client.stream("GET", download_url, headers=headers) as r:
                    if r.status_code != 200:
                        logger.error(f"Error descargando media desde Meta: {r.status_code}")
                        return
                    async for chunk in r.aiter_bytes():
                        yield chunk
            
        return StreamingResponse(
            event_generator(),
            status_code=200,
            media_type=mime_type
        )
    except HTTPException as he:
        # Propagar directamente excepciones HTTP conocidas (como el 401 del token expirado)
        if msg_type == "image":
            from fastapi.responses import Response
            return Response(content=fallback_svg, media_type="image/svg+xml")
        raise he
    except Exception as e:
        logger.error(f"Error al servir media proxy para ID {media_id}: {e}")
        if msg_type == "image":
            from fastapi.responses import Response
            return Response(content=fallback_svg, media_type="image/svg+xml")
        raise HTTPException(status_code=500, detail=str(e))


class MessageEdit(BaseModel):
    content: str

@router.delete("/messages/{message_id}")
async def delete_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Elimina un mensaje del historial del CRM.
    """
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
        
    contact = db.query(Contact).filter(Contact.id == msg.contact_id).first()
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para borrar este mensaje.")
        
    db.delete(msg)
    db.commit()
    
    ws_payload = {
        "event": "message_deleted",
        "data": {
            "id": message_id,
            "contact_id": contact.id
        }
    }
    await manager.broadcast(ws_payload)
    return {"status": "success", "message": "Mensaje eliminado"}


@router.patch("/messages/{message_id}", response_model=MessageResponse)
async def edit_message(
    message_id: int,
    payload: MessageEdit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Edita el contenido de un mensaje existente en el CRM.
    """
    msg = db.query(Message).filter(Message.id == message_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
        
    contact = db.query(Contact).filter(Contact.id == msg.contact_id).first()
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para editar este mensaje.")
        
    msg.content = payload.content
    db.add(msg)
    db.commit()
    db.refresh(msg)
    
    ws_payload = {
        "event": "message_edited",
        "data": {
            "id": msg.id,
            "contact_id": contact.id,
            "content": msg.content,
            "message_type": msg.message_type,
            "created_at": msg.created_at.isoformat()
        }
    }
    await manager.broadcast(ws_payload)
    return msg


class AvatarUpdate(BaseModel):
    avatar_url: str

@router.post("/{contact_id}/avatar")
async def update_contact_avatar(
    contact_id: int,
    payload: AvatarUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Actualiza la URL de la imagen de perfil (avatar) de un contacto.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
        
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para actualizar este avatar.")
        
    contact.avatar_url = payload.avatar_url
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return {"status": "success", "avatar_url": contact.avatar_url}


@router.delete("/{contact_id}")
def delete_contact_and_chat(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Elimina un contacto y todo su historial de chats de forma permanente.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
        
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para eliminar este chat.")
        
    db.query(Message).filter(Message.contact_id == contact_id).delete()
    db.query(Contact).filter(Contact.id == contact_id).delete()
    db.commit()
    return {"status": "success", "message": "Chat y contacto eliminados correctamente"}


from pydantic import BaseModel
from app.models.base import LeadActivityLog
from app.services.activity import record_activity

class NoteCreate(BaseModel):
    note: str

@router.get("/{contact_id}/activities")
def get_contact_activities(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Recupera el historial de actividades (Timeline) de un contacto.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
        
    # Control de acceso: Asesores solo acceden a sus contactos asignados
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para acceder a las actividades de este contacto."
        )
        
    logs = db.query(LeadActivityLog)\
        .filter(LeadActivityLog.contact_id == contact_id)\
        .order_by(desc(LeadActivityLog.created_at))\
        .all()
        
    results = []
    for log in logs:
        user_name = "Sistema"
        if log.user_id:
            user = db.query(User).filter(User.id == log.user_id).first()
            if user:
                user_name = user.full_name
        
        results.append({
            "id": log.id,
            "contact_id": log.contact_id,
            "user_id": log.user_id,
            "user_name": user_name,
            "activity_type": log.activity_type,
            "description": log.description,
            "created_at": log.created_at.isoformat()
        })
        
    return results


@router.post("/{contact_id}/notes")
def add_internal_note(
    contact_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Agrega una nota interna manual a la línea de tiempo del contacto.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
        
    if current_user.role != "admin" and contact.assigned_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes permiso para agregar notas a este contacto.")
        
    log_entry = record_activity(
        db=db,
        contact_id=contact_id,
        activity_type="internal_note",
        description=payload.note,
        user_id=current_user.id
    )
    
    return {
        "status": "success",
        "id": log_entry.id,
        "user_name": current_user.full_name,
        "activity_type": log_entry.activity_type,
        "description": log_entry.description,
        "created_at": log_entry.created_at.isoformat()
    }


from app.services.audit_logger import get_audit_logs

@router.get("/logs/audit")
def fetch_audit_logs(
    db: Session = Depends(get_db)
):
    """
    Retorna los registros de auditoría y diagnóstico en vivo para la consola del CRM.
    Combina la tabla event_audit_trail de Neon DB con los logs del sistema.
    """
    from app.services.audit_logger import audit_logs
    from sqlalchemy import text

    system_logs = list(audit_logs)

    try:
        sql = """
            SELECT a.id, a.trace_id, a.contact_id, a.timestamp, a.source, a.event_type, a.execution_path, a.payload, c.first_name, c.phone
            FROM event_audit_trail a
            LEFT JOIN contacts c ON a.contact_id = c.id
            ORDER BY a.id DESC LIMIT 50
        """
        db_rows = db.execute(text(sql)).fetchall()

        db_logs = []
        for r in reversed(db_rows):
            ts = r[3].strftime("%I:%M:%S %p") if r[3] else "00:00:00 AM"
            source = r[4] or "SYSTEM"
            event_type = r[5] or "INFO"
            exec_path = r[6] or "N/A"
            payload_str = str(r[7] or "")
            contact_str = f"Cliente #{r[2]} ({r[8] or ''} {r[9] or ''})".strip() if r[2] else "Sistema"

            level = "error" if "error" in event_type.lower() or "fail" in event_type.lower() else "success" if "success" in event_type.lower() or "send" in event_type.lower() else "info"
            msg_type = "ai" if "ai" in source.lower() else "webhook" if "webhook" in source.lower() or "meta" in source.lower() or "whatsapp" in source.lower() else "system"

            formatted_msg = f"🔎 [{source}] {contact_str} ➔ {event_type} | Código: {exec_path} | Metadatos: {payload_str[:160]}"

            db_logs.append({
                "id": r[0] + 100000,
                "timestamp": ts,
                "type": msg_type,
                "level": level,
                "message": formatted_msg
            })

        return system_logs + db_logs
    except Exception as e:
        logger.error(f"Error cargando event_audit_trail en fetch_audit_logs: {e}")
        return system_logs



@router.post("/{contact_id}/corrections", response_model=CorrectionResponse)
def add_chat_correction(
    contact_id: int,
    payload: CorrectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Registra una corrección realizada por un asesor a una respuesta de la IA.
    Esta corrección se inyectará en el prompt de Sofi para su aprendizaje continuo.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
        
    correction = AuditCorrection(
        contact_id=contact_id,
        message_id=payload.message_id,
        query=payload.query,
        corrected_response=payload.corrected_response,
        is_approved=True
    )
    db.add(correction)
    db.commit()
    db.refresh(correction)

    from app.services.activity import record_activity
    record_activity(
        db=db,
        contact_id=contact_id,
        activity_type="ai_correction",
        description=f"Asesor {current_user.full_name} registró una corrección al entrenamiento de Sofi: '{payload.query[:60]}...'",
        user_id=current_user.id
    )

    logger.info(f"Corrección registrada exitosamente por {current_user.full_name} para el contacto {contact_id}")
    return correction


async def process_ai_trigger_background(contact_id: int, user_id: int, user_name: str):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return

        last_msg = db.query(Message).filter(
            Message.contact_id == contact_id,
            Message.sender_type == SenderType.CONTACT
        ).order_by(desc(Message.created_at)).first()

        last_text = last_msg.content if last_msg else "Hola"

        from app.services.ai_engine import ai_engine
        from app.services.whatsapp import whatsapp_service
        
        ai_reply = await ai_engine.generate_autopilot_reply(
            db=db,
            contact=contact,
            last_message=last_text
        )

        if not ai_reply:
            return

        db_ai_msg = Message(
            contact_id=contact.id,
            sender_type=SenderType.AI,
            channel=contact.source if contact.source in [ChannelType.WHATSAPP, ChannelType.INSTAGRAM] else ChannelType.WHATSAPP,
            message_type=MessageType.TEXT,
            content=ai_reply,
            status=MessageStatus.SENT
        )
        db.add(db_ai_msg)
        db.commit()
        db.refresh(db_ai_msg)

        if contact.source == "Instagram" or contact.phone.startswith("IG-"):
            if contact.facebook_page_scoped_id:
                from app.services.meta_api import meta_api_service
                external_res = await meta_api_service.send_instagram_dm(
                    recipient_psid=contact.facebook_page_scoped_id,
                    message_text=ai_reply
                )
                if external_res and "message_id" in external_res:
                    db_ai_msg.external_message_id = external_res.get("message_id")
                    db_ai_msg.status = MessageStatus.DELIVERED
                    db.add(db_ai_msg)
                    db.commit()
        else:
            import re
            raw_b = re.findall(r'\[\s*(.*?)\s*\]', ai_reply or "")
            parsed_b = [m.strip() for m in raw_b if m.strip() and not m.strip().startswith("http")]

            if 1 <= len(parsed_b) <= 3:
                btn_objs = [{"id": f"btn_chat_{idx+1}", "title": b[:20]} for idx, b in enumerate(parsed_b)]
                clean_body = re.sub(r'\[\s*.*?\s*\](?:\s*\|\s*\[\s*.*?\s*\])*', '', ai_reply).strip() or ai_reply
                external_res = await whatsapp_service.send_interactive_buttons(
                    to_phone=contact.phone,
                    body_text=clean_body,
                    buttons=btn_objs,
                    header_text="ANCLA Special Projects",
                    footer_text="Selecciona tu opción",
                    db=db
                )
            else:
                external_res = await whatsapp_service.send_text_message(
                    to_phone=contact.phone,
                    message_text=ai_reply,
                    db=db
                )

            if external_res and "messages" in external_res:
                db_ai_msg.external_message_id = external_res["messages"][0].get("id")
                db_ai_msg.status = MessageStatus.DELIVERED
                db.add(db_ai_msg)
                db.commit()

        ws_payload = {
            "event": "message_received",
            "data": {
                "id": db_ai_msg.id,
                "contact_id": contact.id,
                "sender_type": db_ai_msg.sender_type,
                "channel": db_ai_msg.channel,
                "message_type": db_ai_msg.message_type,
                "content": db_ai_msg.content,
                "status": db_ai_msg.status,
                "created_at": db_ai_msg.created_at.isoformat()
            }
        }
        await manager.broadcast(ws_payload)

        from app.services.activity import record_activity
        record_activity(
            db=db,
            contact_id=contact_id,
            activity_type="ai_triggered_manually",
            description=f"El asesor {user_name} forzó una respuesta automática de Sofi IA.",
            user_id=user_id
        )
    except Exception as e:
        logger.error(f"Error en procesado en segundo plano de trigger_ai: {e}")
    finally:
        db.close()


@router.post("/{contact_id}/force-ai")
@router.post("/{contact_id}/trigger-ai")
async def trigger_ai_response(
    contact_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Fuerza a la IA a responder al último mensaje enviado por el cliente.
    Habilita el chatbot de forma automática y procesa en segundo plano para evitar timeouts.
    """
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # Forzar piloto automático activado
    contact.chatbot_enabled = True
    db.add(contact)
    db.commit()

    # Ejecutar en segundo plano de forma asíncrona e instantánea
    background_tasks.add_task(process_ai_trigger_background, contact_id, current_user.id, current_user.full_name)

    return {"status": "success", "message": "Respuesta de Sofi iniciada en segundo plano..."}


@router.websocket("/ws")
async def chat_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...)
):
    """
    Endpoint WebSocket de producción con autenticación JWT y latido (Ping/Pong).
    """
    from app.config import settings
    from jose import jwt, JWTError
    user_id = None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        sub = payload.get("sub")
        if sub is not None:
            user_id = int(sub)
    except (JWTError, ValueError, TypeError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
    except Exception as e:
        logger.error(f"Excepción en WebSocket de asesor #{user_id}: {e}")
        manager.disconnect(websocket, user_id)


