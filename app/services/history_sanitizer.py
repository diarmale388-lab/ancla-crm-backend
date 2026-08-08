"""
app/services/history_sanitizer.py
----------------------------------
Middleware de Sanitización de Historial Conversacional para Sofi AI.
Filtra plantillas antiguas de bienvenida, mensajes duplicados y errores del sistema 
antes de enviar el array de mensajes al Modelo LLM (OpenRouter / Claude / GPT-4o).
"""

from typing import List
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage

def sanitize_chat_history_for_llm(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Sanitiza y limpia la lista de mensajes de la conversación antes de enviarla al LLM.
    - Filtra plantillas antiguas de bienvenida con botones de corchetes o emojis redundantes.
    - Evita duplicación de mensajes idénticos consecutivos.
    - Mantiene el mensaje inicial relevante y los últimos 12 mensajes clave para ahorrar contexto y evitar alucinaciones.
    """
    if not messages:
        return []

    cleaned: List[BaseMessage] = []
    seen_welcome_template = False
    
    # Patrones de plantillas antiguas redundantes que causaban el 'efecto eco'
    legacy_template_patterns = [
        "gracias por escribir a ancla special projects",
        "hemos recibido tu solicitud para coordinar tu **asesoría virtual",
        "disponemos de horarios diurnos de **lunes a viernes",
        "1️⃣ **visita presencial en showroom armenia**",
        "2️⃣ **asesoría virtual / llamada comercial**",
        "disponemos de horarios diurnos de lunes a viernes",
        "martes 28 de julio",
        "showroom del 28 y 29",
        "gran inauguración"
    ]

    for msg in messages:
        if isinstance(msg, SystemMessage):
            cleaned.append(msg)
            continue
            
        content_lower = str(getattr(msg, "content", "") or "").lower()

        # 1. Filtrar 100% TODAS las plantillas de bienvenida u ofertas caducadas antiguas
        is_legacy_template = any(pattern in content_lower for pattern in legacy_template_patterns)
        if is_legacy_template:
            continue

        # 2. Evitar mensajes idénticos consecutivos enviados por la IA
        if cleaned and isinstance(msg, AIMessage) and isinstance(cleaned[-1], AIMessage):
            if cleaned[-1].content == msg.content:
                continue

        cleaned.append(msg)

    # 3. Truncamiento inteligente: Mantener máximo los últimos 14 mensajes
    if len(cleaned) > 14:
        first_msg = cleaned[0]
        recent_msgs = cleaned[-13:]
        if first_msg not in recent_msgs:
            cleaned = [first_msg] + recent_msgs
        else:
            cleaned = recent_msgs

    return cleaned
