"""
ai_agent/nodes/simple_interaction.py
--------------------------------------
Nodo de respuesta rápida para interacciones simples (simple_interaction_node).
Maneja saludos cortos, confirmaciones afirmativas directas y cierres conversacionales con baja latencia.
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage
from ai_agent.state import AgentState


async def simple_interaction_node(state: AgentState) -> Dict[str, Any]:
    """
    Nodo de paso simple: Delegación directa a sales_expert_node (Claude 3.5 Sonnet).
    Garantiza CERO textos estáticos o plantillas hardcodeadas.
    """
    from ai_agent.nodes.sales_expert import sales_expert_node
    return await sales_expert_node(state)


