import os, logging
from sqlalchemy.orm import Session
from app.models.base import Contact, PipelineStage
from app.services.activity import record_activity

logger = logging.getLogger("qualification_service")

def analyze_and_qualify_lead(db: Session, contact: Contact, message_text: str) -> bool:
    """
    Analiza el contenido del mensaje entrante para calificar automáticamente al lead,
    aplicando decaimiento por inactividad y clasificación semántica inteligente por LLM
    con fallback a heurísticas de palabras clave.
    """
    from datetime import datetime
    
    # 0. Decaimiento de Score por Inactividad (Score Decay)
    # Si ha pasado más de 5 días sin interacción del contacto, su calificación baja un peldaño
    if contact.updated_at and contact.qualification_level:
        dias_inactivo = (datetime.utcnow() - contact.updated_at).days
        if dias_inactivo >= 5:
            old_level = contact.qualification_level
            if old_level == "potencial":
                contact.qualification_level = "explorador"
                contact.qualification_notes = f"Decaimiento automático por inactividad comercial de {dias_inactivo} días."
                db.add(contact)
                db.commit()
                logger.info(f"Lead {contact.id} decaimiento de score: potencial -> explorador")
            elif old_level == "explorador":
                contact.qualification_level = "curioso"
                contact.qualification_notes = f"Decaimiento automático por inactividad comercial de {dias_inactivo} días."
                db.add(contact)
                db.commit()
                logger.info(f"Lead {contact.id} decaimiento de score: explorador -> curioso")

    text_lower = message_text.lower()
    updated = False

    # Automatic Email Extraction via Regex
    import re
    email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", message_text)
    if email_match:
        found_email = email_match.group(0).lower().strip()
        if contact.email != found_email:
            contact.email = found_email
            updated = True
            logger.info(f"Correo extraído automáticamente para lead #{contact.id}: {found_email}")
            try:
                from app.core.socket_manager import manager
                import asyncio
                ws_update = {
                    "event": "contact_details_updated",
                    "data": {
                        "contact_id": contact.id,
                        "email": contact.email
                    }
                }
                asyncio.create_task(manager.broadcast(ws_update))
            except Exception as ws_err:
                logger.error(f"Error transmitiendo email por WS: {ws_err}")

    # 1. Calificación semántica inteligente por LLM (Gemini/OpenRouter)
    api_key = None
    from app.models.base import SystemSetting
    from app.config import settings
    import httpx
    import json
    
    db_key = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
    if db_key and db_key.value:
        api_key = db_key.value
    if not api_key:
        api_key = settings.GEMINI_API_KEY
        
    if api_key:
        is_openrouter = api_key.startswith("sk-or-v1")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        if is_openrouter:
            url = "https://openrouter.ai/api/v1/chat/completions"
            
        system_instruction = (
            "Eres un clasificador de prospectos experto para la constructora de casas modulares ANCLA Special Projects.\n"
            "Analiza el mensaje del cliente y clasifica:\n"
            "1. 'interest_product': Una de: 'Glamping', 'Flex Home', 'Cuartos Fríos', 'Bodegas Industriales' (o null si no lo menciona).\n"
            "2. 'qualification_level': Una de: 'potencial' (si tiene lote/terreno, quiere comprar pronto, de contado o crédito, o agendar cita activa), 'explorador' (si está buscando lote, planea a futuro, en unos meses, cotizando con calma) o 'curioso' (si no da indicios de lote, responde evasivo o no muestra intención clara de compra).\n"
            "3. 'notes': Una breve nota comercial justificando tu clasificación.\n\n"
            "Devuelve EXCLUSIVAMENTE un objeto JSON válido con las llaves exactas: 'interest_product', 'qualification_level', 'notes'."
        )
        
        payload = {}
        if is_openrouter:
            payload = {
                "model": os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat"),
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": message_text}
                ],
                "temperature": 0.0,
                "response_format": {"type": "json_object"}
            }
        else:
            payload = {
                "contents": [{"parts": [{"text": message_text}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {
                    "temperature": 0.0,
                    "responseMimeType": "application/json"
                }
            }
            
        try:
            headers = {}
            if is_openrouter:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            # analyze_and_qualify_lead es una llamada síncrona, usamos httpx.Client() síncrono.
            with httpx.Client() as sync_client:
                res = sync_client.post(url, json=payload, headers=headers, timeout=5.0)
                if res.status_code == 200:
                    data = res.json()
                    raw_text = ""
                    if is_openrouter:
                        raw_text = data["choices"][0]["message"]["content"].strip()
                    else:
                        raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    
                    parsed = json.loads(raw_text)
                    
                    interest = parsed.get("interest_product")
                    level = parsed.get("qualification_level")
                    notes = parsed.get("notes")
                    
                    updated_flag = False
                    if interest and interest in ["Glamping", "Flex Home", "Cuartos Fríos", "Bodegas Industriales"] and contact.interest_product != interest:
                        contact.interest_product = interest
                        updated_flag = True
                    if level and level in ["potencial", "explorador", "curioso"] and contact.qualification_level != level:
                        contact.qualification_level = level
                        contact.qualification_notes = notes
                        updated_flag = True
                        
                        # Mover etapa en Kanban
                        if level == "potencial" and contact.pipeline_stage_id == 1:
                            stages = db.query(PipelineStage).all()
                            stage_map = {s.name: s.id for s in stages}
                            iniciado_id = stage_map.get("Contacto Iniciado")
                            if iniciado_id:
                                contact.pipeline_stage_id = iniciado_id
                                
                        # Registrar actividad
                        level_display = {
                            "potencial": "🟢 Cliente Potencial (Alta Intención)",
                            "explorador": "🟡 Prospecto en Exploración (Nurturing)",
                            "curioso": "🔴 Prospecto Inicial / Curioso"
                        }.get(level, level)
                        record_activity(
                            db=db,
                            contact_id=contact.id,
                            activity_type="lead_qualified",
                            description=f"[LLM] Lead clasificado como '{level_display}' en línea '{contact.interest_product or 'General'}'. Nota: {notes}",
                            user_id=None
                        )
                    
                    if updated_flag:
                        db.add(contact)
                        db.commit()
                        db.refresh(contact)
                        return True
        except Exception as e:
            logger.error(f"Error en clasificación semántica LLM (usando fallback de palabras clave): {e}")
    
    # 2. Fallback de Detección de Línea de Interés de Producto (Palabras Clave)
    detected_interest = None
    if any(k in text_lower for k in ["cápsula", "capsula", "linvig", "glamping", "eco lodge", "renta corta", "cabina"]):
        detected_interest = "Glamping"
    elif any(k in text_lower for k in ["flex home", "expandible", "casa expandible", "vivienda", "casa modular"]):
        detected_interest = "Flex Home"
    elif any(k in text_lower for k in ["cuarto frío", "cuarto frio", "cámara de refrigeración", "camara de refrigeracion", "copeland", "monoblock", "congelac", "refrigerac"]):
        detected_interest = "Cuartos Fríos"
    elif any(k in text_lower for k in ["bodega", "galpon", "industrial", "estructura en acero", "galvaniz", "aula modular"]):
        detected_interest = "Bodegas Industriales"

    if detected_interest and contact.interest_product != detected_interest:
        contact.interest_product = detected_interest
        updated = True

    # 3. Fallback de Detección de Calificación de Intención (Palabras Clave)
    new_level = contact.qualification_level
    notes_list = []
    if contact.qualification_notes:
        notes_list = [contact.qualification_notes]

    # Indicadores de ALTA INTENCIÓN (🟢 potencial)
    high_intent = any(k in text_lower for k in [
        "tengo el lote", "tengo terreno", "tengo el terreno", "terreno propio", "lote propio",
        "tengo la planta", "comprar este mes", "inmediato", "agendar", "cita", "reunion", "reunión",
        "cuándo podemos hablar", "lista de precios", "pago de contado", "crédito aprobado"
    ])

    # Indicadores de MEDIANO PLAZO / EXPLORACIÓN (🟡 explorador)
    medium_intent = any(k in text_lower for k in [
        "buscando lote", "en proceso de compra", "el otro año", "en unos meses", "futuro",
        "más adelante", "mas adelante", "cotizar para más adelante", "cotizando", "para el próximo año"
    ])

    if high_intent:
        new_level = "potencial"
        notes_list.append("Lead calificado con ALTA intencionalidad de compra o terreno confirmado.")
    elif medium_intent and contact.qualification_level != "potencial":
        new_level = "explorador"
        notes_list.append("Lead en proceso de prospección / exploración a mediano plazo.")
    elif not contact.qualification_level:
        new_level = "curioso"

    if new_level != contact.qualification_level:
        old_level = contact.qualification_level or "Sin Clasificar"
        contact.qualification_level = new_level
        contact.qualification_notes = " | ".join(dict.fromkeys(notes_list))
        updated = True
        
        level_display = {
            "potencial": "🟢 Cliente Potencial (Alta Intención)",
            "explorador": "🟡 Prospecto en Exploración (Nurturing)",
            "curioso": "🔴 Prospecto Inicial / Curioso"
        }.get(new_level, new_level)
        
        record_activity(
            db=db,
            contact_id=contact.id,
            activity_type="lead_qualified",
            description=f"Lead clasificado como '{level_display}' en línea '{contact.interest_product or 'General'}'.",
            user_id=None
        )

        if new_level == "potencial" and contact.pipeline_stage_id == 1:
            stages = db.query(PipelineStage).all()
            stage_map = {s.name: s.id for s in stages}
            iniciado_id = stage_map.get("Contacto Iniciado")
            if iniciado_id:
                contact.pipeline_stage_id = iniciado_id

    if updated:
        db.add(contact)
        db.commit()
        db.refresh(contact)

    return updated
