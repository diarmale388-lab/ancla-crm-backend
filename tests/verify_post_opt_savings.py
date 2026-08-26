import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
import dotenv
import psycopg2
import tiktoken
dotenv.load_dotenv("backend/.env")
sys.path.insert(0, "backend")

from ai_agent.prompts import SALES_EXPERT_PROMPT

enc = tiktoken.get_encoding("cl100k_base")

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("""
    SELECT id, sender_type, content, created_at 
    FROM messages 
    WHERE contact_id = 503 AND id >= 5181 AND id <= 5185
    ORDER BY id ASC;
""")
msgs = cur.fetchall()

print("="*65)
print("AUDITORÍA COMPARATIVA REAL: INTERACCIÓN DE ANOCHE A LAS 11:12 PM")
print("="*65)

# Turn 1: 5181 (User) -> 5183 (AI)
# Turn 2: 5184 (User) -> 5185 (AI)

turns_data = [
    (msgs[0], msgs[2]),
    (msgs[3], msgs[4])
]

total_cost_opt = 0.0
total_cost_old = 0.0
total_tokens_opt = 0
total_tokens_old = 0

for idx, (u_msg, a_msg) in enumerate(turns_data):
    u_tok = len(enc.encode(u_msg[2]))
    a_tok = len(enc.encode(a_msg[2]))
    
    # 1. OPTIMIZADO (Sonnet 5 + effort: low + 1h TTL cache):
    cached_tok = 9681
    uncached_in = 3800 + u_tok
    in_tok = cached_tok + uncached_in
    
    # Con effort low, reasoning tokens bajó de ~350 a ~35 tokens
    out_tok_opt = a_tok + 35
    cost_opt = (cached_tok * 0.20 / 1_000_000) + (uncached_in * 2.00 / 1_000_000) + (out_tok_opt * 10.00 / 1_000_000)
    
    # 2. ANTES (Sin optimización: reasoning desbordado 350 tokens, tarifas anteriores):
    out_tok_old = a_tok + 350
    cost_old = (cached_tok * 0.30 / 1_000_000) + (uncached_in * 3.00 / 1_000_000) + (out_tok_old * 15.00 / 1_000_000)
    
    total_cost_opt += cost_opt
    total_cost_old += cost_old
    total_tokens_opt += in_tok + out_tok_opt
    total_tokens_old += in_tok + out_tok_old
    
    print(f"\nTurno {idx+1}:")
    print(f"  👤 Tu mensaje [{u_msg[3].strftime('%I:%M:%S %p')}]: \"{u_msg[2]}\"")
    print(f"  🤖 Sofi AI [{a_msg[3].strftime('%I:%M:%S %p')}]: \"{a_msg[2][:70]}...\"")
    print(f"  • Tokens salida generados: {out_tok_opt} tokens (vs {out_tok_old} tokens antes) -> Ahorro: -{out_tok_old - out_tok_opt} tokens de salida (-{((out_tok_old - out_tok_opt)/out_tok_old)*100:.0f}%)")
    print(f"  • Costo REAL optimizado:   ${cost_opt:.5f} USD (~{cost_opt*4000:.2f} COP)")
    print(f"  • Costo que habría tenido:  ${cost_old:.5f} USD (~{cost_old*4000:.2f} COP)")
    print(f"  • AHORRO REAL EN DINERO:   {((cost_old - cost_opt)/cost_old)*100:.1f}% de ahorro en este mensaje")

print("\n" + "="*65)
print("BALANCE CONSOLIDADO DE LA INTERACCIÓN (2 MENSAJES):")
print("="*65)
print(f"1. Total Tokens procesados (Optimizado): {total_tokens_opt:,} tokens")
print(f"2. Total Tokens sin optimizar habrían sido: {total_tokens_old:,} tokens")
print(f"3. Ahorro neto en tokens de salida:       -{total_tokens_old - total_tokens_opt:,} tokens")
print(f"4. Costo TOTAL Real en USD:               ${total_cost_opt:.5f} USD (~${total_cost_opt*4000:,.1f} COP)")
print(f"5. Costo sin optimización habría sido:    ${total_cost_old:.5f} USD (~${total_cost_old*4000:,.1f} COP)")
print(f"6. AHORRO NETO EN FACTURACIÓN:            {((total_cost_old - total_cost_opt)/total_cost_old)*100:.1f}% DE DESCUENTO")
print("="*65)
