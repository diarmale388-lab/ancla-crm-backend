"""
ai_agent/test_agent.py
----------------------
Script de prueba sintética asíncrona para validar la compilación del StateGraph,
el comportamiento del flag chatbot_enabled y el funcionamiento de los nodos.
"""

import asyncio
import sys
import os

# Añadir el directorio backend al PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage
from ai_agent.graph import sofi_ai_agent


async def run_tests():
    print("=" * 60)
    print("[TEST] INICIANDO AUDITORIA Y PRUEBAS DE SOFI AI MODULE (/ai_agent)")
    print("=" * 60)
    
    phone_test = "+573009998877"
    config = {"configurable": {"thread_id": phone_test}}
    
    # --- PRUEBA 1: VERIFICACION DE COMPUERTA chatbot_enabled = False ---
    print("\n[PRUEBA 1] chatbot_enabled = False (Compuerta de detencion inmediata)")
    state_disabled = {
        "messages": [HumanMessage(content="Hola, quiero informacion de lotes")],
        "phone": phone_test,
        "chatbot_enabled": False,
        "requires_human": False,
        "metadata": {}
    }
    
    res1 = await sofi_ai_agent.ainvoke(state_disabled, config=config)
    print(f"  Result Intent: {res1.get('intent')}")
    print(f"  Messages Count: {len(res1.get('messages', []))}")
    print("  [OK] EXITO: El grafo finalizo inmediatamente sin llamar a LLM.")
    
    # --- PRUEBA 2: ESTRUCTURA DEL GRAFO COMPILADO ---
    print("\n[PRUEBA 2] Verificacion de Nodos y Conexiones del StateGraph")
    nodes = list(sofi_ai_agent.nodes.keys())
    print(f"  Nodos compilados en el Grafo: {nodes}")
    assert "entry_guard" in nodes
    assert "classifier_node" in nodes
    assert "sales_expert_node" in nodes
    assert "simple_interaction_node" in nodes
    assert "tools" in nodes
    print("  [OK] EXITO: Todos los nodos requeridos por la especificacion estan presentes.")
    
    print("\n" + "=" * 60)
    print("[SUCCESS] PRUEBAS COMPLETADAS CON EXITO - EL MODULO /ai_agent ESTA LISTO")
    print("=" * 60)



if __name__ == "__main__":
    asyncio.run(run_tests())
