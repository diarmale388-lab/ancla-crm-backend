import asyncio
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, "backend")
import dotenv
dotenv.load_dotenv("backend/.env")

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from ai_agent.config import ai_settings

api_key = os.getenv("OPENROUTER_API_KEY")

async def test_all_three():
    print("=========================================================")
    print("VERIFICACIÓN EN TIEMPO REAL DE LA SUITE HÍBRIDA DE 3 IAs")
    print("=========================================================")

    # 1. Google Gemini (Clasificador & Portero)
    print(f"\n1. ⚡ PROBANDO RECEPCIÓN & CLASIFICADOR: [{ai_settings.CLASSIFIER_MODEL}]")
    llm_gemini = ChatOpenAI(
        model=ai_settings.CLASSIFIER_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.0,
        max_tokens=50
    )
    res_g = await llm_gemini.ainvoke([HumanMessage(content="Responde solo: 'Gemini 3.7 Flash Operando al 100%'")])
    print(f"   👉 Estado: ACTIVO Y RESPONDIENDO")
    print(f"   👉 Salida: {res_g.content}")

    # 2. Anthropic Claude Sonnet (Ventas, WhatsApp & Cierre)
    print(f"\n2. 👑 PROBANDO VENTAS & WHATSAPP: [{ai_settings.SALES_EXPERT_MODEL}]")
    llm_claude = ChatOpenAI(
        model=ai_settings.SALES_EXPERT_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.3,
        max_tokens=60
    )
    res_c = await llm_claude.ainvoke([HumanMessage(content="Responde solo: 'Claude Sonnet 5 Operando al 100%'")])
    print(f"   👉 Estado: ACTIVO Y RESPONDIENDO")
    print(f"   👉 Salida: {res_c.content}")

    # 3. DeepSeek (Resúmenes Ejecutivos & Documentos)
    print(f"\n3. 📄 PROBANDO RESÚMENES & DOCUMENTOS: [{ai_settings.DOCS_EXPERT_MODEL}]")
    llm_deepseek = ChatOpenAI(
        model=ai_settings.DOCS_EXPERT_MODEL,
        openai_api_key=api_key,
        openai_api_base=ai_settings.OPENROUTER_BASE_URL,
        temperature=0.2,
        max_tokens=50
    )
    res_d = await llm_deepseek.ainvoke([HumanMessage(content="Responde solo: 'DeepSeek V4-Pro Operando al 100%'")])
    print(f"   👉 Estado: ACTIVO Y RESPONDIENDO")
    print(f"   👉 Salida: {res_d.content}")

    print("\n=========================================================")
    print("✅ LAS 3 IAS ESTÁN 100% OPERATIVAS Y CONECTADAS")
    print("=========================================================")

if __name__ == "__main__":
    asyncio.run(test_all_three())
