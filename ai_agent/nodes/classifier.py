"""
ai_agent/nodes/classifier.py
-----------------------------
Nodo clasificador inicial de intención y extractor de Formularios Meta Ads (classifier_node).
Utiliza 'google/gemini-3.5-flash-lite' vía OpenRouter para clasificar la intención y extraer silenciosamente
las respuestas de formularios de Meta Ads hacia AgentState.
"""

import json
from typing import Dict, Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from ai_agent.config import ai_settings
from ai_agent.state import AgentState
from ai_agent.prompts import CLASSIFIER_PROMPT


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
        max_tokens=300,
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
    
    # 1. Extracción silenciosa por Python
    python_extracted = _extract_meta_ads_python(last_message)
    if python_extracted:
        meta_ads_lead_data.update(python_extracted)
        if "nombre" in python_extracted and not user_name:
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
            if raw_intent == "HUMAN_HANDOVER":
                intent = "HUMAN_HANDOVER"
                requires_human = True
            
            llm_lead_data = data.get("meta_ads_lead_data")
            if isinstance(llm_lead_data, dict):
                clean_llm_data = {k: v for k, v in llm_lead_data.items() if v and v != "..."}
                meta_ads_lead_data.update(clean_llm_data)
                if not user_name and clean_llm_data.get("nombre"):
                    user_name = clean_llm_data["nombre"]
        else:
            lowered = last_message.lower()
            if any(w in lowered for w in ["humano", "asesor", "persona", "hablar con alguien", "queja", "reclamo"]):
                intent = "HUMAN_HANDOVER"
                requires_human = True

    except Exception as e:
        lowered = last_message.lower()
        if any(w in lowered for w in ["humano", "asesor", "persona", "hablar con alguien"]):
            intent = "HUMAN_HANDOVER"
            requires_human = True

    result = {
        "intent": intent,
        "requires_human": requires_human,
        "meta_ads_lead_data": meta_ads_lead_data if meta_ads_lead_data else None
    }
    if user_name:
        result["user_name"] = user_name

    return result


