import asyncio
import os
import dotenv
dotenv.load_dotenv("backend/.env")
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

api_key = os.getenv("OPENROUTER_API_KEY")

async def test_model(model_name: str):
    print(f"\n--- Testing: {model_name} ---")
    try:
        llm = ChatOpenAI(
            model=model_name,
            openai_api_key=api_key,
            openai_api_base="https://openrouter.ai/api/v1",
            temperature=0.3,
            max_tokens=50
        )
        res = await llm.ainvoke([HumanMessage(content="Di exactamente: 'Conexion Exitosa'")])
        print(f"SUCCESS [{model_name}]: {res.content}")
        return True
    except Exception as e:
        print(f"FAILED [{model_name}]: {e}")
        return False

async def main():
    candidates = [
        "anthropic/claude-sonnet-5",
        "~anthropic/claude-sonnet-latest",
        "anthropic/claude-sonnet-4.6",
        "anthropic/claude-sonnet-4.5",
        "google/gemini-3.7-flash",
        "google/gemini-3.5-flash",
        "google/gemini-2.5-flash",
        "~google/gemini-flash-latest",
        "deepseek/deepseek-chat",
        "deepseek/deepseek-v4-pro"
    ]
    for c in candidates:
        await test_model(c)

if __name__ == "__main__":
    asyncio.run(main())
