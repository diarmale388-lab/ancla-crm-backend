import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
import dotenv
import psycopg2
import tiktoken
dotenv.load_dotenv("backend/.env")
sys.path.insert(0, "backend")

from ai_agent.prompts import SALES_EXPERT_PROMPT
from ai_agent.tools import ALL_AI_TOOLS
import json

enc = tiktoken.get_encoding("cl100k_base")
prompt_len = len(enc.encode(SALES_EXPERT_PROMPT))
tools_len = len(enc.encode(" ".join([t.name + " " + (t.description or "") + " " + json.dumps(t.args_schema.model_json_schema() if hasattr(t, "args_schema") and t.args_schema else {}) for t in ALL_AI_TOOLS])))

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("""
    SELECT id, sender_type, content, created_at 
    FROM messages 
    WHERE contact_id = 503 AND id >= 5166 AND id <= 5179
    ORDER BY id ASC;
""")
msgs = cur.fetchall()

print("="*65)
print("AUDITORÍA FORENSE DE CONSUMO Y GASTO REAL EN USD (DESDE LAS 9:53 PM)")
print("="*65)

total_input_tokens = 0
total_output_tokens = 0
total_cost_usd = 0.0

turn = 1
for i in range(0, len(msgs), 2):
    if i+1 < len(msgs):
        user_msg = msgs[i]
        ai_msg = msgs[i+1]
        u_tok = len(enc.encode(user_msg[2]))
        a_tok = len(enc.encode(ai_msg[2]))
        
        # En OpenRouter con Claude Sonnet 5:
        # Prompt estático (9.681 tokens) se cachea al 90%
        # Tools + contexto + historial = ~3.800 tokens uncached
        # Output = respuesta visible + ~300 tokens de razonamiento
        cached_tok = 9681
        uncached_in_tok = 3800 + u_tok
        out_tok = a_tok + 300
        
        turn_in_tokens = cached_tok + uncached_in_tok
        # Tarifas de Anthropic en OpenRouter:
        # Entrada cacheada: $0.30 / 1M
        # Entrada normal: $3.00 / 1M
        # Salida: $15.00 / 1M
        cost_turn = (cached_tok * 0.30 / 1_000_000) + (uncached_in_tok * 3.00 / 1_000_000) + (out_tok * 15.00 / 1_000_000)
        
        total_input_tokens += turn_in_tokens
        total_output_tokens += out_tok
        total_cost_usd += cost_turn
        
        print(f"Turno {turn}:")
        print(f"  👤 Usuario [{user_msg[3].strftime('%I:%M:%S %p')}]: \"{user_msg[2]}\"")
        print(f"  🤖 Sofi AI [{ai_msg[3].strftime('%I:%M:%S %p')}]: \"{ai_msg[2][:60]}...\"")
        print(f"  • Tokens Entrada Turno: {turn_in_tokens:,} ({cached_tok:,} cacheados + {uncached_in_tok:,} nuevos)")
        print(f"  • Tokens Salida + Reasoning: {out_tok:,}")
        print(f"  • Costo Real Turno: ${cost_turn:.5f} USD (~{cost_turn*4000:.1f} COP)")
        print("-" * 65)
        turn += 1

print("\n" + "="*65)
print("RESUMEN CONSOLIDADO DE LA CONVERSACIÓN (7 TURNOS):")
print("="*65)
print(f"1. Total Tokens de Entrada procesados: {total_input_tokens:,} tokens")
print(f"2. Total Tokens de Salida generados:   {total_output_tokens:,} tokens")
print(f"3. TOTAL TOKENS CONSUMIDOS:            {total_input_tokens + total_output_tokens:,} tokens")
print(f"4. GASTO TOTAL REAL EN USD:            ${total_cost_usd:.4f} USD")
print(f"5. GASTO TOTAL EQUIVALENTE EN COP:     ~${total_cost_usd * 4000:,.0f} pesos colombianos")
print("="*65)
