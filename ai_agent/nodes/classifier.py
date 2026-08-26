"""
ai_agent/nodes/classifier.py
-----------------------------
Nodo clasificador inicial de intención y extractor de Formularios Meta Ads (classifier_node).
Utiliza 'google/gemini-3.5-flash-lite' vía OpenRouter para clasificar la intención y extraer silenciosamente
las respuestas de formularios de Meta Ads hacia AgentState.
"""

import json
import re
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from ai_agent.config import ai_settings
from ai_agent.state import AgentState
from ai_agent.prompts import CLASSIFIER_PROMPT


_PRICE_OBJECTION_KEYWORDS = [
    "precio", "precios", "cuesta", "cuánto vale", "cuanto vale", "cuánto cuesta", "cuanto cuesta",
    "valor del m2", "valor por m2", "metro cuadrado", "cotiza", "cotización", "cotizacion",
    "catálogo", "catalogo", "brochure", "folleto", "fotos de los acabados", "cuánto sale", "cuanto sale"
]

_SCHEDULING_KEYWORDS = [
    "cita", "agendar", "agenda", "disponib", "horario", "reagendar", "reprogramar",
    "cancela", "cancelar", "cancélame", "cancelame", "virtual", "presencial", "showroom",
    "llamada telef", "llamada", "confirmo", "confirmado", "nos vemos", "lunes", "martes",
    "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo", "mañana",
    "manana", "esta noche"
]

# Patrón de hora explícita (ej: "8 pm", "8:00 pm", "5am") con límite de palabra: evita
# falsos positivos de "am"/"pm" como subcadena suelta dentro de palabras comunes en
# español (ej. "glAMping", "fAMilia").
_TIME_PATTERN = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b", re.IGNORECASE)


def _keyword_hit(text_lower: str, keywords) -> bool:
    return any(k in text_lower for k in keywords)


def _has_scheduling_signal(text_lower: str) -> bool:
    return _keyword_hit(text_lower, _SCHEDULING_KEYWORDS) or bool(_TIME_PATTERN.search(text_lower))


# Frases ESTRICTAS de escalamiento humano explícito, usadas como respaldo heurístico
# (dummy-key / excepción del LLM). Deliberadamente NO incluye palabras sueltas como
# "persona" o "asesor" (aparecen con frecuencia en texto benigno, ej. formularios
# Meta Ads con "Persona Natural") para evitar falsos positivos de HUMAN_HANDOVER.
_HUMAN_ESCALATION_STRICT_PHRASES = [
    "persona real", "humano", "hablar con un humano", "no me responde un bot",
    "quiero una persona", "hablar con alguien", "hablar con un asesor", "atención humana",
    "queja", "reclamo"
]


def _extract_meta_ads_python(text: str) -> Dict[str, Any]:
    """Helper Python para extracción por patrones de texto de formularios Meta Ads."""
    extracted = {}
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    for line in lines:
        if ":" in line or "?" in line:
            parts = line.split(":", 1) if ":" in line else line.split("?", 1)
            key = parts[0].strip().lower()
            val = parts[1].strip() if len(parts) > 1 else ""
            if not val and ":" in parts[0]:
                continue
            if "terreno" in key:
                extracted["tiene_terreno"] = val
            elif any(k in key for k in ["ciudad", "municipio", "lote", "ubicacion", "ubicación"]):
                extracted["ciudad_lote"] = val
            elif any(k in key for k in ["modelo", "casa", "capsula", "cápsula", "proyecto"]):
                extracted["modelo_interes"] = val
            elif any(k in key for k in ["nombre", "cliente"]):
                extracted["nombre"] = val
            elif any(k in key for k in ["nota", "comentario", "observacion", "observación", "preferencia"]):
                extracted["notas_cliente"] = val
    return extracted


async def classifier_node(state: AgentState) -> Dict[str, Any]:
    """
    Nodo inicial portero: Realiza ÚNICAMENTE revisión silenciosa de Meta Ads y Atención Humana.
    Todo el tráfico conversacional se asigna a 'SALES_CONVERSATION' para ser respondido dinámicamente por Claude.
    """
    messages = state.get("messages", [])
    if not messages:
        return {"intent": "SALES_CONVERSATION"}
    
    last_message = messages[-1].content if hasattr(messages[-1], "content") else str(messages[-1])
    
    api_key = ai_settings.OPENROUTER_API_KEY.strip() or "sk-or-v1-dummy-key-for-testing"
    
    llm = ChatOpenAI(
        model=ai_settings.CLASSIFIER_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.0,
        max_tokens=500,
        default_headers={
            "HTTP-Referer": ai_settings.HTTP_REFERER,
            "X-Title": ai_settings.SITE_NAME,
        }
    )
    
    prompt_messages = [
        SystemMessage(content=CLASSIFIER_PROMPT),
        HumanMessage(content=f"Mensaje del cliente:\n{last_message}")
    ]
    
    intent = "SALES_CONVERSATION"
    requires_human = False
    meta_ads_lead_data = dict(state.get("meta_ads_lead_data") or {})
    user_name = state.get("user_name")

    lowered_last = last_message.lower().strip()
    # Heurística base (usada como fallback si el LLM falla o como refuerzo silencioso)
    has_price_objection = _keyword_hit(lowered_last, _PRICE_OBJECTION_KEYWORDS)
    has_scheduling_request = (not has_price_objection) and _has_scheduling_signal(lowered_last)

    # 1. Extracción silenciosa por Python
    python_extracted = _extract_meta_ads_python(last_message)
    if python_extracted:
        meta_ads_lead_data.update(python_extracted)
        if "nombre" in python_extracted and python_extracted["nombre"]:
            user_name = python_extracted["nombre"]

    # 2. Evaluación silenciosa vía LLM o Heurística
    try:
        if api_key != "sk-or-v1-dummy-key-for-testing":
            response = await llm.ainvoke(prompt_messages)
            content = response.content.strip()
            
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()
                
            data = json.loads(content)
            raw_intent = data.get("intent", "SALES_CONVERSATION")
            
            # Salvaguarda: si el mensaje menciona modalidad de asesoría/cita, NUNCA es HUMAN_HANDOVER
            is_modality_selection = any(m in lowered_last for m in ["virtual", "presencial", "showroom", "llamada", "asesoría", "asesoria", "cita", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "imposible", "no puedo"])
            
            if raw_intent == "HUMAN_HANDOVER" and not is_modality_selection:
                # Solo si pide un ser humano explícito (ej: "persona real", "humano", "hablar con alguien real")
                if any(w in lowered_last for w in ["persona real", "humano", "hablar con un humano", "no me responde un bot", "quiero una persona"]):
                    intent = "HUMAN_HANDOVER"
                    requires_human = True
                else:
                    intent = "SALES_CONVERSATION"
                    requires_human = False
            else:
                intent = "SALES_CONVERSATION"
                requires_human = False

            # Señales estructuradas del router (con la heurística como respaldo si el campo falta o es inválido)
            if isinstance(data.get("has_price_or_brochure_objection"), bool):
                has_price_objection = data["has_price_or_brochure_objection"]
            if isinstance(data.get("has_scheduling_request"), bool):
                has_scheduling_request = data["has_scheduling_request"] and not has_price_objection

            llm_lead_data = data.get("meta_ads_lead_data")
            if isinstance(llm_lead_data, dict):
                clean_llm_data = {k: v for k, v in llm_lead_data.items() if v and v != "..."}
                meta_ads_lead_data.update(clean_llm_data)
                if not user_name and clean_llm_data.get("nombre"):
                    user_name = clean_llm_data["nombre"]
        else:
            if _keyword_hit(lowered_last, _HUMAN_ESCALATION_STRICT_PHRASES):
                intent = "HUMAN_HANDOVER"
                requires_human = True

    except Exception as e:
        if _keyword_hit(lowered_last, _HUMAN_ESCALATION_STRICT_PHRASES):
            intent = "HUMAN_HANDOVER"
            requires_human = True

    # 3. Enrutamiento hacia el nodo visible correcto (Regla de Oro: Precio > Agenda mecánica > Ventas general)
    if intent == "HUMAN_HANDOVER" or requires_human:
        active_agent = "human_handover_node"
    elif has_price_objection:
        active_agent = "sales_expert_node"
    elif has_scheduling_request:
        active_agent = "scheduling_node"
    else:
        active_agent = "sales_expert_node"

    result = {
        "intent": intent,
        "requires_human": requires_human,
        "meta_ads_lead_data": meta_ads_lead_data if meta_ads_lead_data else None,
        "active_agent": active_agent
    }
    if user_name:
        result["user_name"] = user_name

    return result


