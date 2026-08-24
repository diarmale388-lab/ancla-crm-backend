import os
import logging
import httpx
import datetime as dt_module
from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models.base import Contact, Availability, Appointment, PipelineStage, SystemSetting, Message, SenderType

logger = logging.getLogger("ai_engine")

class AIEngine:
    def __init__(self):
        # API Key por defecto de las variables de entorno
        self.api_key = settings.GEMINI_API_KEY
        self.model = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def _get_api_key(self, db: Session) -> Optional[str]:
        """
        Retorna la clave API de Gemini configurada. Prioriza la base de datos sobre el archivo .env.
        """
        db_key = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
        if db_key and db_key.value:
            return db_key.value
        return self.api_key

    def get_dynamic_days_list(self) -> str:
        import datetime as dt
        now = dt.datetime.now()
        days_es = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        months_es = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        
        lines = []
        num = 1
        for i in range(1, 8):
            target_date = now + dt.timedelta(days=i)
            if target_date.weekday() == 6: # Skip Sunday
                continue
            if num > 6:
                break
            day_name = days_es[target_date.weekday()]
            month_name = months_es[target_date.month]
            rel_label = " (Mañana)" if i == 1 else ""
            lines.append(f"• **{num}️⃣ {day_name} {target_date.day} de {month_name}{rel_label}**")
            num += 1
            
        return "\n".join(lines)

    def get_dynamic_showroom_options(self, is_virtual: bool = False) -> str:
        """DEPRECADO: Plantilla estática deshabilitada. Sofi AI responde dinámicamente vía Claude 3.5 Sonnet."""
        return "¡Hola! Con mucho gusto te asesoramos con la información de nuestros proyectos modulares."


    async def generate_copilot_suggestion(self, conversation_history: List[Dict[str, Any]], db: Session = None) -> str:
        """
        Genera una sugerencia de respuesta (Copiloto) basada en los últimos mensajes usando Google Gemini.
        """
        api_key = self.api_key
        if db:
            api_key = self._get_api_key(db)

        if not api_key:
            return "¡Hola! ¿En qué proyecto modular o industrial te podemos asesorar hoy?"

        url = f"{self.api_url}?key={api_key}"
        
        system_instruction = (
            "Actúas como un copiloto de IA en un CRM. Sugiere una respuesta concisa, "
            "persuasiva y amigable al último mensaje del cliente. Mantén la respuesta en español."
        )
        
        chat_context = []
        for msg in conversation_history[-10:]:
            role = "model" if msg["sender_type"] in ["user", "ai"] else "user"
            chat_context.append(f"{role}: {msg['content']}")

        prompt = "Historial del chat:\n" + "\n".join(chat_context) + "\n\nSugiere la mejor respuesta:"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 200}
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=12.0)
                if response.status_code == 200:
                    data = response.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    return "¡Hola! Con mucho gusto te ayudamos con tu consulta."
        except Exception:
            return "¡Hola! Con mucho gusto te ayudamos con tu consulta."

    async def generate_autopilot_reply(self, db: Session, contact: Contact, last_message: str) -> Optional[str]:
        """
        Genera una respuesta autónoma utilizando el nuevo módulo /ai_agent (LangGraph + OpenRouter).
        Delegación 100% limpia sin heurísticas antiguas.
        """
        if not contact or not contact.chatbot_enabled:
            return None

        full_message_payload = last_message

        from ai_agent.graph import sofi_ai_agent
        from langchain_core.messages import HumanMessage, AIMessage

        # Cargar historial relacional directamente desde la base de datos PostgreSQL.
        # IMPORTANTE: cada mensaje recibe un `id` determinístico basado en su PK de BD para que el
        # reducer `add_messages` de LangGraph pueda deduplicar por id en vez de acumular duplicados
        # cada vez que se reenvía el mismo historial reciente sobre el thread_id persistente del cliente.
        db_msgs = db.query(Message).filter(Message.contact_id == contact.id).order_by(Message.created_at.asc()).all()
        langchain_msgs = []
        for m in db_msgs[-10:]:
            msg_id = f"db_{m.id}"
            if m.sender_type == SenderType.CONTACT:
                langchain_msgs.append(HumanMessage(content=m.content or "", id=msg_id))
            elif m.sender_type == SenderType.AI:
                langchain_msgs.append(AIMessage(content=m.content or "", id=msg_id))

        if langchain_msgs and isinstance(langchain_msgs[-1], HumanMessage):
            langchain_msgs[-1] = HumanMessage(content=full_message_payload, id=langchain_msgs[-1].id)
        elif not langchain_msgs or not isinstance(langchain_msgs[-1], HumanMessage):
            import uuid
            langchain_msgs.append(HumanMessage(content=full_message_payload, id=f"live_{uuid.uuid4().hex}"))

        try:
            print(f"\n[AI_ENGINE] Historial cargado de la BD ({len(db_msgs)} mensajes en total, {len(langchain_msgs)} enviados al LLM):")
            for idx, m_item in enumerate(langchain_msgs):
                safe_prev = str(getattr(m_item, 'content', ''))[:100].encode('ascii', errors='replace').decode('ascii')
                print(f"  - [{idx+1}] {m_item.__class__.__name__}: {safe_prev}")
        except Exception:
            pass

        # Inyectar estado relacional real desde la base de datos PostgreSQL
        from app.models.base import Appointment
        import datetime as dt_tz
        try:
            from zoneinfo import ZoneInfo
            bogota_now = dt_tz.datetime.now(ZoneInfo("America/Bogota"))
        except Exception:
            bogota_now = dt_tz.datetime.now(dt_tz.timezone(dt_tz.timedelta(hours=-5)))

        active_appt = db.query(Appointment).filter(
            Appointment.contact_id == contact.id,
            Appointment.status.in_(["CONFIRMED", "PENDING"]),
            Appointment.datetime >= bogota_now.replace(tzinfo=None) - dt_tz.timedelta(hours=2)
        ).order_by(Appointment.datetime.desc()).first()

        active_appt_str = "Ninguna"
        if active_appt:
            mod_str = getattr(active_appt, 'modality', None) or contact.scheduling_state or "Virtual"
            active_appt_str = f"{active_appt.datetime.strftime('%A %d de %B a las %I:%M %p')} (Modalidad: {mod_str})"

        # ID DE HILO ESTABLE POR CLIENTE: usar únicamente el teléfono (sin timestamp) para que
        # LangGraph reutilice el mismo checkpoint de memoria en cada turno de la conversación,
        # en lugar de crear un hilo nuevo (y huérfano) por cada mensaje entrante.
        thread_key = str(contact.phone)
        config = {"configurable": {"thread_id": thread_key}}
        input_state = {
            "messages": langchain_msgs,
            "phone": contact.phone,
            "chatbot_enabled": contact.chatbot_enabled,
            "user_name": f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
            "requires_human": False,
            "metadata": {
                "scheduling_state": contact.scheduling_state,
                "has_land": contact.lot_status or "No especificado",
                "location": contact.lot_city or "No especificado",
                "active_appointment": active_appt_str,
                "contact_id": contact.id
            }
        }

        print(f"[AI_ENGINE] Invocando LangGraph sofi_ai_agent con Teléfono={contact.phone}, CitaActiva='{active_appt_str}'...")
        logger.info(f"[AI_ENGINE] Invocando LangGraph sofi_ai_agent con Teléfono={contact.phone}")

        try:
            final_state = await sofi_ai_agent.ainvoke(input_state, config=config)
            initial_msg_count = len(input_state.get("messages", []))
            all_state_msgs = final_state.get("messages", [])
            new_msgs = all_state_msgs[initial_msg_count:] if len(all_state_msgs) > initial_msg_count else all_state_msgs[-1:]

            save_appointment_executed = False
            for msg in all_state_msgs:
                if getattr(msg, "type", "") == "tool" and getattr(msg, "name", "") == "save_appointment":
                    save_appointment_executed = True
                    break
                for tc in getattr(msg, "tool_calls", None) or []:
                    tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                    if tc_name == "save_appointment":
                        save_appointment_executed = True
                        break
                if save_appointment_executed:
                    break

            # Extraer y combinar de forma limpia los mensajes generados por la IA
            ai_parts = []
            for msg in new_msgs:
                if getattr(msg, "type", "") == "ai" or isinstance(msg, AIMessage):
                    content_val = getattr(msg, "content", "")
                    if isinstance(content_val, list):
                        text_parts = [item.get("text", "") if isinstance(item, dict) else str(item) for item in content_val]
                        content_str = "".join(text_parts).strip()
                    else:
                        content_str = str(content_val or "").strip()
                    
                    if content_str and content_str.lower() != "none":
                        # Limpiar residuos de herramientas internas ("voy a consultar...", etc.)
                        clean_lines = [
                            l for l in content_str.split("\n")
                            if not any(l.strip().lower().startswith(prefix) for prefix in [
                                "voy a consultar", "permíteme consultar", "voy a revisar",
                                "voy a proceder", "un momento, por favor", "un momento por favor"
                            ])
                        ]
                        cleaned_chunk = "\n".join(clean_lines).strip()
                        if cleaned_chunk:
                            ai_parts.append(cleaned_chunk)

            final_ai_msg = None
            if ai_parts:
                final_ai_msg = ai_parts[-1].strip()

            if final_ai_msg:
                full_reply = final_ai_msg.strip()
                try:
                    safe_log = full_reply[:140].encode('ascii', errors='replace').decode('ascii')
                    print(f"[AI_ENGINE] Respuesta generada exitosamente por el Agente: '{safe_log}...'")
                except Exception:
                    pass
                logger.info("[AI_ENGINE] Respuesta generada exitosamente por el Agente")
                return full_reply

            # El grafo se ejecutó sin excepciones pero no produjo ningún texto útil para el cliente
            # (ej. el LLM solo emitió llamadas a herramientas sin mensaje final). Para NUNCA dejar
            # al cliente en silencio, se entrega un mensaje de cortesía honesto.
            print("[AI_ENGINE] Advertencia: No se encontró ningún mensaje válido en el estado final del agente.")
            logger.warning("[AI_ENGINE] El grafo no produjo texto final; se envía mensaje de cortesía de respaldo")
            return self._get_fallback_reply(contact)

        except Exception as e:
            import traceback
            err_str = traceback.format_exc()
            print(f"\n[FALLBACK] Error crítico al invocar /ai_agent: {e}")
            print(f"[FALLBACK] Traceback completo:\n{err_str}")
            logger.error(f"[FALLBACK] Error invocando módulo autónomo /ai_agent: {e}\n{err_str}")
            
            try:
                from app.services.blackbox_auditor import blackbox_auditor
                blackbox_auditor.log_event(
                    event_type="AI_ENGINE_INVOCATION_ERROR",
                    severity="ERROR",
                    description=f"Fallo invocando módulo autonomo /ai_agent para {contact.phone}: {e}",
                    contact_id=contact.id,
                    contact_phone=contact.phone,
                    input_payload=last_message,
                    error_traceback=err_str,
                    model_used="openai/gpt-4o",
                    resolved_status="INVESTIGATING",
                    db=db
                )
            except Exception:
                pass

            # CORRECCIÓN CRÍTICA: antes se retornaba None y el cliente se quedaba sin respuesta ante
            # un timeout o error del agente. Ahora se entrega siempre un mensaje honesto de cortesía.
            return self._get_fallback_reply(contact)

    @staticmethod
    def _get_fallback_reply(contact: Contact) -> str:
        """Mensaje de respaldo honesto para nunca dejar al cliente en silencio ante fallos técnicos."""
        name = (contact.first_name or "").strip()
        greeting = f"¡Hola {name}!" if name else "¡Hola!"
        return (
            f"{greeting} 🙏 Estamos teniendo un inconveniente técnico momentáneo para procesar tu mensaje. "
            f"En breve uno de nuestros asesores de ANCLA Special Projects te contactará personalmente por "
            f"este mismo medio."
        )

ai_engine = AIEngine()
