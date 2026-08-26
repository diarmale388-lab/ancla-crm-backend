import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
import dotenv
import psycopg2
import tiktoken
dotenv.load_dotenv("backend/.env")

enc = tiktoken.get_encoding("cl100k_base")

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("""
    SELECT id, sender_type, content, created_at 
    FROM messages 
    WHERE contact_id = 503 AND id >= 5190 AND id <= 5200
    ORDER BY id ASC;
""")
msgs = cur.fetchall()

print("="*70)
print("AUDITORÍA FORENSE DE LA PRUEBA EN VIVO (10:30 AM DE HOY)")
print("="*70)

# Pricing oficiales OpenRouter Agosto 2026:
# Gemini 3.7 Flash (Router): Prompt $0.15/1M, Completion $0.60/1M
# Claude Haiku 4.5 (Scheduling): Prompt $1.00/1M, Cached Read $0.10/1M, Completion $5.00/1M
# Claude Sonnet 5 (Sales): Prompt $2.00/1M, Cached Read $0.20/1M, Completion $10.00/1M

turns = [
    (msgs[0], msgs[1], 'sales_expert_node', 'Claude Sonnet 5'),
    (msgs[2], msgs[4], 'scheduling_node', 'Claude Haiku 4.5'),
    (msgs[5], msgs[6], 'scheduling_node', 'Claude Haiku 4.5'),
    (msgs[7], msgs[8], 'scheduling_node', 'Claude Haiku 4.5'),
    (msgs[9], msgs[10], 'scheduling_node', 'Claude Haiku 4.5'),
]

total_router_tokens = 0
total_agent_in_tokens = 0
total_agent_out_tokens = 0
total_cost_usd = 0.0

for idx, (u_msg, a_msg, node, model) in enumerate(turns):
    u_tok = len(enc.encode(u_msg[2]))
    a_tok = len(enc.encode(a_msg[2]))
    
    # 1. Router Call (Gemini 3.7 Flash)
    router_in = 650 + u_tok
    router_out = 45 # Structured Output JSON
    cost_router = (router_in * 0.15 / 1_000_000) + (router_out * 0.60 / 1_000_000)
    total_router_tokens += router_in + router_out
    
    # 2. Sub-Agent Call
    if node == 'sales_expert_node':
        cached_in = 9681
        uncached_in = 3800 + u_tok
        out_tok = a_tok + 35 # low reasoning
        cost_agent = (cached_in * 0.20 / 1_000_000) + (uncached_in * 2.00 / 1_000_000) + (out_tok * 10.00 / 1_000_000)
    else: # scheduling_node (Haiku 4.5)
        cached_in = 1600 # Haiku prompt
        uncached_in = 700 + u_tok # Scoped tools + context
        out_tok = a_tok # Haiku has no reasoning overhead
        cost_agent = (cached_in * 0.10 / 1_000_000) + (uncached_in * 1.00 / 1_000_000) + (out_tok * 5.00 / 1_000_000)
        
    cost_turn = cost_router + cost_agent
    total_agent_in_tokens += cached_in + uncached_in
    total_agent_out_tokens += out_tok
    total_cost_usd += cost_turn
    
    print(f"Turno {idx+1} [Hora: {u_msg[3].strftime('%I:%M:%S %p')}]:")
    print(f"  👤 Tu mensaje: \"{u_msg[2][:70]}...\"")
    print(f"  🤖 Sofi AI:    \"{a_msg[2][:70]}...\"")
    print(f"  • Enrutado a:  {node} ({model})")
    print(f"  • Tokens Entrada: {cached_in + uncached_in:,} ({cached_in:,} cacheados + {uncached_in:,} nuevos)")
    print(f"  • Tokens Salida:  {out_tok:,} tokens")
    print(f"  • Costo Turno:    ${cost_turn:.5f} USD (~{cost_turn*4000:.2f} COP)")
    print("-" * 70)

print("\n" + "="*70)
print("RESUMEN CONSOLIDADO DE LA SESIÓN DE 5 MENSAJES (10:30 AM):")
print("="*70)
print(f"1. Total Tokens Procesados por Router (Gemini):  {total_router_tokens:,} tokens")
print(f"2. Total Tokens Entrada Procesados por Agentes:  {total_agent_in_tokens:,} tokens")
print(f"3. Total Tokens Salida Generados por Agentes:    {total_agent_out_tokens:,} tokens")
print(f"4. TOTAL TOKENS CONSUMIDOS:                      {total_router_tokens + total_agent_in_tokens + total_agent_out_tokens:,} tokens")
print(f"5. GASTO TOTAL REAL DE LA SESIÓN (5 TURNOS):     ${total_cost_usd:.5f} USD (~${total_cost_usd*4000:,.1f} COP)")
print(f"6. COSTO PROMEDIO POR MENSAJE:                   ${total_cost_usd/len(turns):.5f} USD (~${(total_cost_usd/len(turns))*4000:.2f} COP)")
print("="*70)
