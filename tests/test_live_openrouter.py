import asyncio
import os
import dotenv
dotenv.load_dotenv("backend/.env")
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

api_key = os.getenv("OPENROUTER_API_KEY")
print(f"Testing OpenRouter with key: {api_key[:12]}...")

llm_claude = ChatOpenAI(
    model="anthropic/claude-3.7-sonnet",
    openai_api_key=api_key,
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0.3,
    max_tokens=50
)

llm_gemini = ChatOpenAI(
    model="google/gemini-2.0-flash-001",
    openai_api_key=api_key,
    openai_api_base="https://openrouter.ai/api/v1",
    temperature=0.3,
    max_tokens=50
)

async def main():
    print("--- 1. Testing Gemini 2.0 Flash ---")
    try:
        res_g = await llm_gemini.ainvoke([HumanMessage(content="Di exactamente: 'Gemini 2.0 Flash Operando'")])
        print("Gemini Response:", res_g.content)
    except Exception as e:
        print("Gemini Error:", e)

    print("\n--- 2. Testing Claude 3.7 Sonnet ---")
    try:
        res_c = await llm_claude.ainvoke([HumanMessage(content="Di exactamente: 'Claude 3.7 Sonnet Operando'")])
        print("Claude Response:", res_c.content)
    except Exception as e:
        print("Claude Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
