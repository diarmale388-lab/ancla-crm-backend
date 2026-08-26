"""
backend/tests/test_multiagent_evals.py
----------------------------------------
Suite de regresión de la Arquitectura Multi-Agente Híbrida de Sofi AI
(Router Gemini con señales estructuradas + scheduling_node en Claude Haiku +
sales_expert_node en Claude Sonnet como única voz para objeciones/calificación).

Valida que el enrutamiento híbrido NO introduzca ninguna de las violaciones que
las 7 Leyes del Contrato Inviolable de Sofi AI prohíben expresamente: precios por
chat, links de Google Meet, amnesia de estado entre agentes o cancelaciones no
deterministas ante muletillas colombianas.

Ejecución:
    pytest backend/tests/test_multiagent_evals.py -v
"""

import sys
import os
import asyncio

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    import dotenv
    dotenv.load_dotenv(os.path.join(backend_dir, ".env"))
except Exception:
    pass

import pytest
from langchain_core.messages import HumanMessage, AIMessage

from ai_agent.graph import sofi_ai_agent


def _default_metadata(**overrides):
    meta = {
        "scheduling_state": "NO_DEFINIDA",
        "has_land": "No especificado",
        "location": "No especificado",
        "active_appointment": "Ninguna",
    }
    meta.update(overrides)
    return meta


async def invoke_sofi(messages, phone="573000000001", user_name="Cliente Test", metadata=None):
    """
    Invoca el grafo compilado completo (sofi_ai_agent) y retorna (final_state, reply_text)
    aplicando la misma regla de extracción atómica (LEY 3 - Mensajes Atómicos) que
    backend/app/services/ai_engine.py: únicamente el ÚLTIMO mensaje de IA generado en
    este turno, jamás la concatenación completa de fragmentos intermedios.
    """
    input_state = {
        "messages": messages,
        "phone": phone,
        "chatbot_enabled": True,
        "user_name": user_name,
        "requires_human": False,
        "metadata": metadata or _default_metadata(),
    }
    config = {"configurable": {"thread_id": f"multiagent_test_{phone}_{int(asyncio.get_event_loop().time() * 1000)}"}}
    final_state = await sofi_ai_agent.ainvoke(input_state, config=config)

    all_msgs = final_state.get("messages", [])
    initial_count = len(messages)
    new_msgs = all_msgs[initial_count:] if len(all_msgs) > initial_count else all_msgs[-1:]

    ai_parts = []
    for m in new_msgs:
        if getattr(m, "type", "") == "ai" or isinstance(m, AIMessage):
            content = getattr(m, "content", "")
            if isinstance(content, list):
                content = "".join([i.get("text", "") if isinstance(i, dict) else str(i) for i in content])
            content_str = str(content or "").strip()
            if content_str and content_str.lower() != "none":
                ai_parts.append(content_str)

    reply = ai_parts[-1] if ai_parts else ""
    return final_state, reply


def _tool_was_called(final_state, tool_name: str) -> bool:
    for m in final_state.get("messages", []):
        if getattr(m, "type", "") == "tool" and getattr(m, "name", "") == tool_name:
            return True
        for tc in getattr(m, "tool_calls", None) or []:
            tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
            if tc_name == tool_name:
                return True
    return False


@pytest.mark.asyncio
async def test_01_mixed_intent_pricing_priority():
    """Un cliente pregunta precio y pide cita a la vez: debe priorizar sales_expert_node y JAMÁS dar precios."""
    messages = [HumanMessage(content="Hola, me interesa una casa en Llanogrande, ¿cuánto vale el m2 y nos vemos el sábado?")]
    final_state, reply = await invoke_sofi(messages, phone="573001111101", user_name="Carlos")

    assert reply, "El agente no generó ninguna respuesta"
    assert "$" not in reply
    assert not any(w in reply.lower() for w in ["millones", " cop", " usd"])
    assert final_state.get("active_agent") == "sales_expert_node", (
        f"Se esperaba enrutamiento a sales_expert_node por objeción de precio, se obtuvo: {final_state.get('active_agent')}"
    )


@pytest.mark.asyncio
async def test_02_anti_amnesia_lot():
    """Si el cliente ya tiene lote registrado en la BD (metadata), el sistema NO debe volver a preguntarlo."""
    messages = [HumanMessage(content="Quiero conocer los acabados de Flex Home")]
    metadata = _default_metadata(has_land="Sí, ya tengo lote propio", location="Pereira")
    final_state, reply = await invoke_sofi(messages, phone="573001111102", user_name="Carlos", metadata=metadata)

    assert reply, "El agente no generó ninguna respuesta"
    lowered = reply.lower()
    assert "¿tienes lote" not in lowered
    assert "¿cuentas con lote" not in lowered
    assert "¿ya tienes terreno" not in lowered
    assert "¿ya cuentas con un terreno" not in lowered


@pytest.mark.asyncio
async def test_03_phone_modality_strict_routes_to_scheduling():
    """Selección pura de modalidad Llamada debe enrutar a scheduling_node y JAMÁS imprimir link de Meet."""
    messages = [HumanMessage(content="Prefiero llamada telefónica, no me gustan las videollamadas")]
    final_state, reply = await invoke_sofi(messages, phone="573001111103", user_name="Carlos")

    assert reply, "El agente no generó ninguna respuesta"
    assert "meet.google.com" not in reply.lower()
    assert "llamada" in reply.lower()
    assert final_state.get("active_agent") == "scheduling_node", (
        f"Se esperaba enrutamiento a scheduling_node (agenda mecánica), se obtuvo: {final_state.get('active_agent')}"
    )


@pytest.mark.asyncio
async def test_04_night_appointment_escalation():
    """Solicitud a las 8:00 PM debe escalar a Liliana León vía solicitar_autorizacion_cita_nocturna."""
    messages = [HumanMessage(content="Solo puedo conectarme a las 8:00 PM por mi trabajo, ¿tienen algún espacio a esa hora?")]
    final_state, reply = await invoke_sofi(messages, phone="573001111104", user_name="Carlos")

    assert reply, "El agente no generó ninguna respuesta"
    mentions_escalation = any(w in reply.lower() for w in ["liliana", "autorización", "autorizacion", "extraordinari"])
    assert mentions_escalation or _tool_was_called(final_state, "solicitar_autorizacion_cita_nocturna"), (
        "Ni el texto ni las herramientas invocadas evidencian escalamiento a Liliana León para horario nocturno."
    )


@pytest.mark.asyncio
async def test_05_colombian_filler_word_cancellation():
    """Una muletilla 'No la verdad no puedo' NO debe cancelar una cita ya confirmada."""
    messages = [HumanMessage(content="No la verdad no puedo a esa hora el jueves")]
    metadata = _default_metadata(
        scheduling_state="VIRTUAL",
        active_appointment="Jueves 27 de Agosto a las 10:00 AM (Modalidad: Virtual)"
    )
    final_state, reply = await invoke_sofi(messages, phone="573001111105", user_name="Carlos", metadata=metadata)

    assert reply, "El agente no generó ninguna respuesta"
    assert "cancelada" not in reply.lower()
