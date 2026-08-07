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

        if contact.scheduling_state:
            contact.scheduling_state = None
            db.add(contact)
            db.commit()

        from ai_agent.graph import sofi_ai_agent
        from langchain_core.messages import HumanMessage

        config = {"configurable": {"thread_id": contact.phone}}
        input_state = {
            "messages": [HumanMessage(content=last_message)],
            "phone": contact.phone,
            "chatbot_enabled": contact.chatbot_enabled,
            "user_name": f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
            "requires_human": False,
            "metadata": {}
        }

        try:
            final_state = await sofi_ai_agent.ainvoke(input_state, config=config)
            messages = final_state.get("messages", [])
            for msg in reversed(messages):
                # Descartar mensajes intermedios que contengan llamadas a herramientas (tool_calls)
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls and len(tool_calls) > 0:
                    continue
                    
                if hasattr(msg, "type") and msg.type == "ai" and hasattr(msg, "content") and str(msg.content).strip():
                    return str(msg.content).strip()
                elif isinstance(msg, dict) and msg.get("role") == "assistant" and str(msg.get("content", "")).strip():
                    if msg.get("tool_calls"):
                        continue
                    return str(msg.get("content")).strip()
            return None

        except Exception as e:
            import traceback
            err_str = traceback.format_exc()
            logger.error(f"Error invocando módulo autónomo /ai_agent: {e}")
            
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

            return "¡Hola! Con mucho gusto te asesoramos sobre nuestras soluciones modulares (Flex Home, Cápsula Living y Cuartos Fríos). ¿En qué ciudad o municipio proyectas tu construcción?"

ai_engine = AIEngine()
