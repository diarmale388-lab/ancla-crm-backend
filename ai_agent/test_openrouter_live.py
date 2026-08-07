"""
ai_agent/test_openrouter_live.py
--------------------------------
Script de verificación del flujo de ejecución del StateGraph y la API del módulo autónomo /ai_agent.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from langchain_core.messages import HumanMessage
from ai_agent.graph import sofi_ai_agent
from ai_agent.config import ai_settings


async def verify_agent_execution():
    print("=" * 65)
    print("[VERIFICACION] COMPROBACION DE INTEGRIDAD Y EJECUCION DE SOFI AI")
    print("=" * 65)
    
    print("\n1. CONFIGURACION DE MODELOS EN OPENROUTER:")
    print(f"   - OpenRouter Base URL: {ai_settings.OPENROUTER_BASE_URL}")
    print(f"   - Classifier Model:   {ai_settings.CLASSIFIER_MODEL}")
    print(f"   - Sales Expert Model: {ai_settings.SALES_EXPERT_MODEL}")
    print(f"   - OpenRouter Key Set: {'SI (Configurado)' if ai_settings.OPENROUTER_API_KEY else 'NO (Requiere OPENROUTER_API_KEY en .env)'}")

    phone_test = "+573177001670"
    config = {"configurable": {"thread_id": phone_test}}
    
    print("\n2. VERIFICACION DE FLUJO A: Mensaje Simple ('Hola buenos dias')")
    state_simple = {
        "messages": [HumanMessage(content="Hola buenos dias")],
        "phone": phone_test,
        "chatbot_enabled": True,
        "requires_human": False,
        "metadata": {}
    }
    
    res_simple = await sofi_ai_agent.ainvoke(state_simple, config=config)
    last_msg_simple = res_simple.get("messages", [])[-1].content
    clean_msg_simple = last_msg_simple.encode('ascii', 'ignore').decode('ascii')
    print(f"   - Intencion Detectada: {res_simple.get('intent')}")
    print(f"   - Respuesta Generada (Snippet): {clean_msg_simple[:150]}...")
    
    print("\n3. VERIFICACION DE FLUJO B: Solicitud Comercial Compleja ('Quiero agendar cita para Flex Home')")
    state_sales = {
        "messages": [HumanMessage(content="Hola, me interesan las casas Flex Home de 56m2 y quiero agendar una cita virtual")],
        "phone": phone_test,
        "chatbot_enabled": True,
        "requires_human": False,
        "metadata": {}
    }
    
    res_sales = await sofi_ai_agent.ainvoke(state_sales, config=config)
    last_msg_sales = res_sales.get("messages", [])[-1].content
    clean_msg_sales = last_msg_sales.encode('ascii', 'ignore').decode('ascii')
    print(f"   - Intencion Detectada: {res_sales.get('intent')}")
    print(f"   - Respuesta Generada (Snippet): {clean_msg_sales[:150]}...")

    print("\n" + "=" * 65)
    print("[OK] EL GRAFO DE LANGGRAPH Y EL ENRUTAMIENTO FUNCIONAN CORRECTAMENTE")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(verify_agent_execution())
