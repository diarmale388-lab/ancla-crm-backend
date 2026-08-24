"""
backend/tests/test_phase2_sofi_stability.py
--------------------------------------------
FASE 2: ESTABILIDAD Y PERFECCIONAMIENTO DE SOFI AI & LANGGRAPH.
Pruebas dirigidas a los 6 puntos de la auditoría:
  1. Memoria persistente (thread_id estable por teléfono, sin checkpoints huérfanos).
  2. Human Handover: nunca deja al cliente en silencio y ejecuta la acción real en el CRM.
  3. `consultar_disponibilidad` nunca devuelve horarios ficticios ante un error.
  4. Los nodos nunca retornan `{"messages": []}` silenciosamente ante un fallo.
  5. `prompts.py` sin ids duplicados y con XML bien formado.
  6. Limpieza: public_pdf_link sin localhost, endpoint de media sin duplicar.

Ejecución:
  python -m pytest backend/tests/test_phase2_sofi_stability.py -v
"""
import sys
import os
import re
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage, AIMessage

from app.main import app
from app.database import SessionLocal
from app.models.base import Contact, Message, SenderType

client = TestClient(app)

TEST_PHONE = "570000000999"


@pytest.fixture(scope="module")
def test_contact():
    db = SessionLocal()
    db.query(Message).filter(Message.contact_id.in_(
        db.query(Contact.id).filter(Contact.phone == TEST_PHONE)
    )).delete(synchronize_session=False)
    db.query(Contact).filter(Contact.phone == TEST_PHONE).delete(synchronize_session=False)
    db.commit()

    contact = Contact(
        first_name="Fase2",
        last_name="Test",
        phone=TEST_PHONE,
        chatbot_enabled=True,
        source="Test Suite"
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    yield contact, db

    db.query(Message).filter(Message.contact_id == contact.id).delete(synchronize_session=False)
    db.query(Contact).filter(Contact.id == contact.id).delete(synchronize_session=False)
    db.commit()
    db.close()


# =============================================================================
# 1. MEMORIA PERSISTENTE (thread_id estable == teléfono, sin timestamp)
# =============================================================================

def test_thread_id_is_stable_phone_without_timestamp():
    """El thread_id generado en ai_engine.py debe ser exactamente el teléfono, sin timestamp."""
    from app.services.ai_engine import ai_engine
    import inspect
    source = inspect.getsource(ai_engine.generate_autopilot_reply)
    assert 'thread_key = str(contact.phone)' in source
    assert 'int(time.time())' not in source, "REGRESIÓN: el thread_id vuelve a incluir timestamp (memoria efímera)"


@pytest.mark.asyncio
async def test_langgraph_memory_persists_across_turns(test_contact):
    """
    Al usar el mismo thread_id (teléfono) en 2 turnos consecutivos, el checkpoint de LangGraph
    debe conservar el historial (no reiniciarse), y no debe duplicar mensajes gracias al id
    determinístico basado en la PK de la base de datos.
    """
    from ai_agent.graph import sofi_ai_agent

    contact, db = test_contact
    thread_id = str(contact.phone)
    config = {"configurable": {"thread_id": thread_id}}

    # Turno 1
    msg1 = Message(contact_id=contact.id, sender_type=SenderType.CONTACT, channel="whatsapp", content="Hola, soy Fase2 Test")
    db.add(msg1)
    db.commit()

    state1 = {
        "messages": [HumanMessage(content="Hola, soy Fase2 Test", id=f"db_{msg1.id}")],
        "phone": contact.phone, "chatbot_enabled": True, "user_name": "Fase2 Test",
        "requires_human": False, "metadata": {"scheduling_state": "NO_DEFINIDA", "has_land": "No especificado", "location": "No especificado", "active_appointment": "Ninguna"}
    }
    result1 = await sofi_ai_agent.ainvoke(state1, config=config)
    count_after_turn1 = len(result1.get("messages", []))
    assert count_after_turn1 >= 2  # al menos el human + 1 ai

    # Turno 2: reenviamos el MISMO mensaje anterior (simulando la recarga completa desde BD que
    # hace ai_engine.py en cada turno) + 1 mensaje nuevo. Si el reducer deduplica por id
    # correctamente, el conteo NO debe duplicar el mensaje del turno 1.
    msg2 = Message(contact_id=contact.id, sender_type=SenderType.CONTACT, channel="whatsapp", content="Una pregunta más")
    db.add(msg2)
    db.commit()

    state2 = {
        "messages": [
            HumanMessage(content="Hola, soy Fase2 Test", id=f"db_{msg1.id}"),
            HumanMessage(content="Una pregunta más", id=f"db_{msg2.id}")
        ],
        "phone": contact.phone, "chatbot_enabled": True, "user_name": "Fase2 Test",
        "requires_human": False, "metadata": {"scheduling_state": "NO_DEFINIDA", "has_land": "No especificado", "location": "No especificado", "active_appointment": "Ninguna"}
    }
    result2 = await sofi_ai_agent.ainvoke(state2, config=config)
    count_after_turn2 = len(result2.get("messages", []))

    # La memoria debe seguir creciendo sobre el MISMO hilo (evidencia de persistencia real)
    assert count_after_turn2 > count_after_turn1, "La memoria no persistió entre turnos usando el mismo thread_id"

    # Verificar que el mensaje "Hola, soy Fase2 Test" NO aparece duplicado en el estado final
    human_texts = [m.content for m in result2["messages"] if getattr(m, "type", "") == "human"]
    occurrences = human_texts.count("Hola, soy Fase2 Test")
    assert occurrences == 1, f"El historial se duplicó ({occurrences} ocurrencias) en vez de deduplicar por id"


# =============================================================================
# 2. HUMAN HANDOVER: nunca silencio + ejecuta la acción real
# =============================================================================

@pytest.mark.asyncio
async def test_human_handover_generates_message_and_disables_chatbot(test_contact):
    """
    Cuando el clasificador detecta HUMAN_HANDOVER, el grafo debe:
      a) Generar un AIMessage de cortesía (nunca terminar en silencio).
      b) Ejecutar request_human_handover, que desactiva chatbot_enabled en el CRM.
    """
    from ai_agent.graph import sofi_ai_agent

    contact, db = test_contact
    contact.chatbot_enabled = True
    db.add(contact)
    db.commit()

    state = {
        "messages": [HumanMessage(content="Quiero hablar con un humano ya, no me responde un bot")],
        "phone": contact.phone, "chatbot_enabled": True, "user_name": "Fase2 Test",
        "requires_human": False, "intent": "HUMAN_HANDOVER",
        "metadata": {"scheduling_state": "NO_DEFINIDA", "has_land": "No especificado", "location": "No especificado", "active_appointment": "Ninguna"}
    }

    # Forzamos directamente el nodo de handover (bypass del clasificador LLM) para aislar el
    # comportamiento determinístico exigido por la auditoría.
    from ai_agent.graph import human_handover_node
    result = await human_handover_node(state)

    ai_msgs = [m for m in result["messages"] if isinstance(m, AIMessage)]
    assert len(ai_msgs) == 1, "El nodo de handover no generó ningún mensaje (cliente en silencio)"
    assert len(ai_msgs[0].content.strip()) > 10

    db.refresh(contact)
    assert contact.chatbot_enabled is False, "request_human_handover no desactivó el chatbot en el CRM"

    # Debe haber quedado constancia interna en la línea de tiempo del chat
    note = db.query(Message).filter(
        Message.contact_id == contact.id,
        Message.content.contains("SOLICITUD DE ATENCIÓN HUMANA")
    ).first()
    assert note is not None, "No se registró la nota interna de handover en el CRM"


def test_route_by_intent_maps_human_handover_to_dedicated_node():
    from ai_agent.graph import route_by_intent
    state = {"intent": "HUMAN_HANDOVER", "requires_human": False}
    assert route_by_intent(state) == "human_handover_node"

    state2 = {"intent": "SALES_CONVERSATION", "requires_human": False}
    assert route_by_intent(state2) == "sales_expert_node"


# =============================================================================
# 3. consultar_disponibilidad: NUNCA horarios ficticios ante error
# =============================================================================

@pytest.mark.asyncio
async def test_consultar_disponibilidad_no_fake_hours_on_error():
    from ai_agent import tools as tools_module

    with patch("ai_agent.tools.dt_tz.datetime") as mock_dt:
        mock_dt.now.side_effect = Exception("Fallo simulado de reloj/BD")
        result = await tools_module.consultar_disponibilidad.ainvoke({"fecha_solicitada": "hoy", "modalidad": "VIRTUAL"})

    assert result["status"] == "error"
    assert result["horarios_disponibles"] == [], "REGRESIÓN: se están devolviendo horarios ficticios hardcodeados"
    for fake_slot in ["10:00 AM", "11:30 AM", "02:00 PM"]:
        assert fake_slot not in str(result), f"Horario ficticio '{fake_slot}' filtrado en la respuesta de error"
    assert "mensaje_para_ia" in result


# =============================================================================
# 4. Fallos silenciosos: NUNCA {"messages": []}
# =============================================================================

@pytest.mark.asyncio
async def test_sales_expert_node_never_returns_empty_messages_on_llm_failure():
    from ai_agent.nodes.sales_expert import sales_expert_node

    state = {
        "messages": [HumanMessage(content="Hola")],
        "phone": "570000000998", "user_name": "Cliente Fallo",
        "metadata": {}
    }

    with patch("ai_agent.nodes.sales_expert.ChatOpenAI") as MockLLM:
        instance = MockLLM.return_value
        instance.bind_tools.return_value.ainvoke = AsyncMock(side_effect=Exception("Timeout simulado del LLM"))
        result = await sales_expert_node(state)

    assert len(result["messages"]) == 1, "sales_expert_node dejó al cliente sin respuesta (messages=[])"
    assert isinstance(result["messages"][0], AIMessage)
    assert len(result["messages"][0].content.strip()) > 10


@pytest.mark.asyncio
async def test_ai_engine_never_returns_none_on_graph_failure(test_contact):
    from app.services.ai_engine import ai_engine

    contact, db = test_contact
    contact.chatbot_enabled = True
    db.add(contact)
    db.commit()

    with patch("ai_agent.graph.sofi_ai_agent.ainvoke", new=AsyncMock(side_effect=Exception("Fallo total simulado del grafo"))):
        reply = await ai_engine.generate_autopilot_reply(db=db, contact=contact, last_message="Hola, hay alguien?")

    assert reply is not None, "REGRESIÓN: ai_engine volvió a dejar al cliente sin respuesta (None) ante un error"
    assert len(reply.strip()) > 10


# =============================================================================
# 5. prompts.py: sin ids duplicados, XML balanceado
# =============================================================================

def test_prompts_no_duplicate_rule_ids_and_balanced_xml():
    from ai_agent import prompts
    content = prompts.SALES_EXPERT_PROMPT
    ids = re.findall(r'<rule id="(\d+)">', content)
    assert len(ids) == len(set(ids)), f"Ids de reglas duplicados detectados: {[i for i in set(ids) if ids.count(i) > 1]}"
    opens = len(re.findall(r'<rule id="\d+">', content))
    closes = len(re.findall(r'</rule>', content))
    assert opens == closes, f"XML de reglas malformado: {opens} aperturas vs {closes} cierres"


# =============================================================================
# 6. Limpieza: public_pdf_link sin localhost + endpoint media sin duplicar
# =============================================================================

def test_public_pdf_link_not_localhost():
    import inspect
    from app.routers import settings as settings_router
    source = inspect.getsource(settings_router.send_proposal_with_ai)
    assert "localhost:8001" not in source, "REGRESIÓN: public_pdf_link sigue apuntando a localhost"
    assert "settings.PUBLIC_BASE_URL" in source


def test_chats_media_endpoint_not_duplicated():
    from app.routers import chats as chats_router_module
    import inspect
    source = inspect.getsource(chats_router_module)
    occurrences = len(re.findall(r'@router\.get\("/media/\{media_id\}"\)', source))
    assert occurrences == 1, f"Se encontraron {occurrences} definiciones de /chats/media/{{media_id}} (se esperaba exactamente 1)"
    assert "get_media_proxy" not in source, "REGRESIÓN: la función duplicada get_media_proxy sigue presente"


def test_frontend_admin_check_has_no_hardcoded_ids():
    """
    Verifica específicamente que el patrón `isAdmin = ... currentUser?.id === <N>` (comprobación
    de administrador con IDs fijos hardcodeados) fue reemplazado por `user.role === 'admin'`.
    No busca el substring suelto de emails/nombres, ya que estos pueden aparecer legítimamente
    en textos de UI no relacionados (placeholders, opciones de un <select>, etc).
    """
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "src")
    offending = []
    for root, _, files in os.walk(frontend_dir):
        for fname in files:
            if fname.endswith((".jsx", ".js")):
                fpath = os.path.join(root, fname)
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                if re.search(r'isAdmin\s*=.*currentUser\?\.id\s*===\s*\d', content):
                    offending.append(fpath)
    assert not offending, f"Comprobación de admin con IDs fijos hardcodeados aún presente en: {offending}"

    expected_files = [
        "components/chat/ChatWindow.jsx",
        "components/common/LeadFichaModal360.jsx",
        "components/chat/SpecialAppointmentBanner.jsx",
        "components/chat/ContactList.jsx",
    ]
    for rel_path in expected_files:
        fpath = os.path.join(frontend_dir, *rel_path.split("/"))
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
        assert re.search(r"isAdmin\s*=\s*currentUser\?\.role\s*===\s*'admin'", content), \
            f"{rel_path} no usa la comprobación limpia user.role === 'admin'"
