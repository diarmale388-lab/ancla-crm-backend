"""
ai_agent/nodes/tool_executor.py
--------------------------------
Nodo ejecutor de herramientas (tool_executor_node).
Ejecuta de manera asíncrona las llamadas a funciones (@tool) solicitadas por el LLM.
"""

from langgraph.prebuilt import ToolNode
from ai_agent.tools import ALL_AI_TOOLS

# Definir el nodo de herramientas reutilizando ToolNode de LangGraph
tool_executor_node = ToolNode(ALL_AI_TOOLS)
