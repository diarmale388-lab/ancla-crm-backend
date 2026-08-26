import asyncio
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "backend")
import dotenv
import psycopg2
dotenv.load_dotenv("backend/.env")

from ai_agent.graph import sofi_ai_agent
from langchain_core.messages import HumanMessage, AIMessage

async def main():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, sender_type, content 
        FROM messages 
        WHERE contact_id = 503 AND id <= 5174
        ORDER BY id ASC;
    """)
    rows = cur.fetchall()[-8:]
    msgs = []
    for r in rows:
        if r[1] == "CONTACT":
            msgs.append(HumanMessage(content=r[2], id=f"db_{r[0]}"))
        elif r[1] == "AI":
            msgs.append(AIMessage(content=r[2], id=f"db_{r[0]}"))
            
    print(f"Loaded {len(msgs)} messages. Last message from user was: {msgs[-1].content}")

    input_state = {
        "messages": msgs,
        "phone": "573177001670",
        "chatbot_enabled": True,
        "user_name": "Diego Machado Leon",
        "requires_human": False,
        "metadata": {
            "scheduling_state": "SPECIAL_REQUEST_PENDING",
            "has_land": "Si",
            "location": "Armenia",
            "active_appointment": "Ninguna",
            "contact_id": 503
        }
    }
    config = {"configurable": {"thread_id": "test_replay_503_sim_v2"}}
    final_state = await sofi_ai_agent.ainvoke(input_state, config=config)
    print(f"Total messages in state: {len(final_state['messages'])}")
    new_msgs = final_state["messages"][len(msgs):]
    print(f"New messages generated ({len(new_msgs)}):")
    for idx, m in enumerate(new_msgs):
        print(f"\n--- New Msg [{idx+1}] ({m.__class__.__name__}) ---")
        print("Content:", repr(getattr(m, "content", "")))
        if getattr(m, "tool_calls", None):
            print("Tool calls:", m.tool_calls)

if __name__ == "__main__":
    asyncio.run(main())
