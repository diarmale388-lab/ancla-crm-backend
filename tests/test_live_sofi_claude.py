import asyncio
import os
import sys
sys.path.insert(0, "backend")
import dotenv
dotenv.load_dotenv("backend/.env")

from ai_agent.graph import build_sofi_graph
from langchain_core.messages import HumanMessage

async def main():
    graph = build_sofi_graph()
    print("Testing live invocation of Sofi AI through Claude Sonnet 5...")
    state = {
        "phone": "573156523581",
        "user_name": "Lorena Soto",
        "chatbot_enabled": True,
        "messages": [HumanMessage(content="Hola, me gustaría saber qué incluye la casa Flex Home")],
        "metadata": {
            "scheduling_state": "INICIAL",
            "has_land": "Sí, en Armenia",
            "location": "Armenia",
            "active_appointment": "Ninguna"
        }
    }
    config = {"configurable": {"thread_id": "test_phone_live_123"}}
    res = await graph.ainvoke(state, config=config)
    last_msg = res["messages"][-1]
    print("\n=======================================================")
    print("RESUESTA EN VIVO GENERADA POR CLAUDE SONNET 5:")
    print("=======================================================")
    print(last_msg.content)
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
