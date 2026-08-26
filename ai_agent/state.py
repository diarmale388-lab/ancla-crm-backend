"""
ai_agent/state.py
-----------------
Definición del estado global del agente (AgentState) en LangGraph.
Asegura la segregación estricta de sesiones utilizando el número telefónico del cliente.
"""

from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """
    Estado global del flujo conversacional para Sofi AI.
    
    Campos:
        messages: Historial acumulado de mensajes intercalados entre Usuario, IA y Tools.
        phone: Identificador único del cliente (utilizado como thread_id en LangGraph).
        chatbot_enabled: Flag booleano de activación del bot entregado por el CRM Core.
        intent: Intención clasificada por classifier_node ("SIMPLE_INTERACTION", "COMPLEX_SALES_QUESTION", "APPOINTMENT_REQUEST", "HUMAN_HANDOVER").
        user_name: Nombre identificado del usuario o cliente prospecto.
        appointment_data: Datos temporales de reserva de cita en proceso.
        meta_ads_lead_data: Datos extraídos silenciosamente de formularios de Meta Ads.
        requires_human: Indicador para pausar el bot y transferir a un ejecutivo humano.
        metadata: Diccionario extensible para metadatos adicionales de la interacción.
        active_agent: Nodo visible seleccionado por el router ("sales_expert_node",
            "scheduling_node" o "human_handover_node"). Opcional para retrocompatibilidad
            con invocaciones que aún no lo establecen (por defecto sales_expert_node).
    """
    messages: Annotated[List[BaseMessage], add_messages]
    phone: str
    chatbot_enabled: bool
    intent: Optional[str]
    user_name: Optional[str]
    appointment_data: Optional[Dict[str, Any]]
    meta_ads_lead_data: Optional[Dict[str, Any]]
    requires_human: bool
    metadata: Dict[str, Any]
    active_agent: Optional[str]

