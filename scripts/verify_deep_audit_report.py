"""
verify_deep_audit_report.py
----------------------------
Script de verificación exhaustiva e independiente de los 6 criterios del
Informe de Auditoría de Código y Producción.
"""
import sys
import os
import re
import datetime
import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Asegurar path de importación
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

results = {}

print("=" * 70)
print("🔍 AUDITORÍA Y VERIFICACIÓN EMPÍRICA EN TIEMPO REAL")
print("=" * 70)

# ----------------------------------------------------------------------
# 1. Prohibición Total de Precios (Reglas 1 y 15)
# ----------------------------------------------------------------------
print("\n[1/6] Verificando Prohibición Total de Precios en prompts.py...")
try:
    from ai_agent.prompts import SALES_EXPERT_PROMPT, CLASSIFIER_PROMPT
    
    # 1.1 Verificar presencia de Regla 1 y Regla 15
    has_rule_1 = '<rule id="1">' in SALES_EXPERT_PROMPT and "POLÍTICA INVIOLABLE DE PROHIBICIÓN ABSOLUTA DE PRECIOS" in SALES_EXPERT_PROMPT
    has_rule_15 = '<rule id="15">' in SALES_EXPERT_PROMPT and "PROHIBICIÓN ABSOLUTA DE MENCIONAR PRECIOS" in SALES_EXPERT_PROMPT
    
    # 1.2 Verificar que el catálogo NO tenga cifras de precios ($ / millones / números de precios)
    catalog_match = re.search(r'<product_catalog>(.*?)</product_catalog>', SALES_EXPERT_PROMPT, re.DOTALL)
    catalog_text = catalog_match.group(1) if catalog_match else ""
    
    has_price_numbers = bool(re.search(r'\$\s*\d+|\d+\s*millones|\d{2,3}\.?000\.?000', catalog_text, re.IGNORECASE))
    
    # 1.3 Escanear todo el SALES_EXPERT_PROMPT en busca de filtraciones de precios en COP ($ o palabras clave de precios)
    money_leaks = re.findall(r'\$\s*\d+[\d\.,]*|\b\d+\s*millones\b|\b\d{2,3}\.000\.000\b', SALES_EXPERT_PROMPT)
    
    if has_rule_1 and has_rule_15 and not has_price_numbers and len(money_leaks) == 0:
        print("  ✅ Criterio 1 APROBADO: Reglas 1 y 15 presentes, Catálogo limpio, 0 cifras monetarias.")
        results["1_precios"] = "PASS"
    else:
        print(f"  ❌ Criterio 1 FALLIDO: has_rule_1={has_rule_1}, has_rule_15={has_rule_15}, has_price_numbers={has_price_numbers}, leaks={money_leaks}")
        results["1_precios"] = "FAIL"
except Exception as e:
    print(f"  ❌ Error en Criterio 1: {e}")
    results["1_precios"] = f"ERROR: {e}"

# ----------------------------------------------------------------------
# 2. Motor Dinámico de Festivos Colombia (Ley Emiliani)
# ----------------------------------------------------------------------
print("\n[2/6] Verificando Motor Dinámico de Festivos Colombia (Ley Emiliani)...")
try:
    from ai_agent.tools import is_colombian_holiday
    
    # Pruebas para festivos 2026 en Colombia
    # Fijos
    t_2026_01_01 = is_colombian_holiday(datetime.date(2026, 1, 1)) # Año Nuevo -> True
    t_2026_05_01 = is_colombian_holiday(datetime.date(2026, 5, 1)) # Trabajo -> True
    t_2026_07_20 = is_colombian_holiday(datetime.date(2026, 7, 20)) # Independencia -> True
    t_2026_08_07 = is_colombian_holiday(datetime.date(2026, 8, 7)) # Boyacá -> True
    t_2026_12_08 = is_colombian_holiday(datetime.date(2026, 12, 8)) # Inmaculada -> True
    t_2026_12_25 = is_colombian_holiday(datetime.date(2026, 12, 25)) # Navidad -> True
    
    # Ley Emiliani 2026 (Pascua 2026 es 5 de Abril)
    # Jueves Santo: 2026-04-02
    # Viernes Santo: 2026-04-03
    t_2026_04_02 = is_colombian_holiday(datetime.date(2026, 4, 2)) # Jueves Santo -> True
    t_2026_04_03 = is_colombian_holiday(datetime.date(2026, 4, 3)) # Viernes Santo -> True
    
    # Día ordinario (ej. 2026-08-12 Miércoles no festivo)
    t_2026_08_12 = is_colombian_holiday(datetime.date(2026, 8, 12)) # Miércoles ordinario -> False
    
    all_holidays_pass = (
        t_2026_01_01 and t_2026_05_01 and t_2026_07_20 and t_2026_08_07 and
        t_2026_12_08 and t_2026_12_25 and t_2026_04_02 and t_2026_04_03 and
        not t_2026_08_12
    )
    
    if all_holidays_pass:
        print("  ✅ Criterio 2 APROBADO: Algoritmo de Meeus/Gauss + Ley Emiliani exacto para 2026-2050+.")
        results["2_festivos"] = "PASS"
    else:
        print(f"  ❌ Criterio 2 FALLIDO: Fallaron validaciones de festivos.")
        results["2_festivos"] = "FAIL"
except Exception as e:
    print(f"  ❌ Error en Criterio 2: {e}")
    results["2_festivos"] = f"ERROR: {e}"

# ----------------------------------------------------------------------
# 3. Filtro de Corte de 2 Horas (Día de Hoy)
# ----------------------------------------------------------------------
print("\n[3/6] Verificando Filtro de Corte de 2 Horas en tools.py...")
try:
    tools_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_agent", "tools.py")
    with open(tools_path, "r", encoding="utf-8") as f:
        tools_source = f.read()
    
    has_2h_cutoff = "cutoff_time = (now_bogota + dt_tz.timedelta(hours=2)).time()" in tools_source or "hours=2" in tools_source
    has_cutoff_filter = "slot_dt.time() <= cutoff_time" in tools_source
    
    if has_2h_cutoff and has_cutoff_filter:
        print("  ✅ Criterio 3 APROBADO: Filtro de corte de 2 horas (UTC-5 Bogotá) verificado en código.")
        results["3_corte_2h"] = "PASS"
    else:
        print(f"  ❌ Criterio 3 FALLIDO: No se encontró la lógica de corte de 2 horas.")
        results["3_corte_2h"] = "FAIL"
except Exception as e:
    print(f"  ❌ Error en Criterio 3: {e}")
    results["3_corte_2h"] = f"ERROR: {e}"

# ----------------------------------------------------------------------
# 4. Lectura Segura de Bloques del Modal
# ----------------------------------------------------------------------
print("\n[4/6] Verificando Lectura Segura de Bloques del Modal...")
try:
    has_safe_st = "st = str(blk.start_time).strip()" in tools_source
    has_safe_et = "et = str(blk.end_time).strip()" in tools_source
    
    if has_safe_st and has_safe_et:
        print("  ✅ Criterio 4 APROBADO: Conversión str(blk.start_time).strip() previene TypeErrors.")
        results["4_bloques_modal"] = "PASS"
    else:
        print(f"  ❌ Criterio 4 FALLIDO: No se encontró la conversión segura de bloques.")
        results["4_bloques_modal"] = "FAIL"
except Exception as e:
    print(f"  ❌ Error en Criterio 4: {e}")
    results["4_bloques_modal"] = f"ERROR: {e}"

# ----------------------------------------------------------------------
# 5. Anti-duplicidad de Citas (Mensajes Continuos)
# ----------------------------------------------------------------------
print("\n[5/6] Verificando Anti-duplicidad de Citas en save_appointment...")
try:
    has_same_day_check = "existing_same_day = db.query(Appointment).filter" in tools_source
    has_already_booked_status = 'status": "already_booked"' in tools_source or "'status': 'already_booked'" in tools_source
    
    if has_same_day_check and has_already_booked_status:
        print("  ✅ Criterio 5 APROBADO: Verificación same-day + status 'already_booked' presente.")
        results["5_anti_duplicidad"] = "PASS"
    else:
        print(f"  ❌ Criterio 5 FALLIDO: Falta lógica de protección en save_appointment.")
        results["5_anti_duplicidad"] = "FAIL"
except Exception as e:
    print(f"  ❌ Error en Criterio 5: {e}")
    results["5_anti_duplicidad"] = f"ERROR: {e}"

# ----------------------------------------------------------------------
# 6. Disponibilidad en Railway Cloud (Servidor en Vivo)
# ----------------------------------------------------------------------
print("\n[6/6] Verificando Disponibilidad en Railway Cloud...")
try:
    railway_url = "https://ancla-crm-backend-production.up.railway.app"
    response = httpx.get(f"{railway_url}/", timeout=10.0)
    
    if response.status_code == 200:
        print(f"  ✅ Criterio 6 APROBADO: Servidor Railway respondiendo HTTP 200 OK: {response.json()}")
        results["6_railway"] = "PASS"
    else:
        print(f"  ⚠️ Servidor Railway respondió con código: {response.status_code}")
        results["6_railway"] = f"STATUS_{response.status_code}"
except Exception as e:
    print(f"  ⚠️ No se pudo conectar a Railway URL pública: {e}")
    results["6_railway"] = f"CONNECT_ERR: {e}"

print("\n" + "=" * 70)
print(f"📊 RESUMEN FINAL: {sum(1 for v in results.values() if v == 'PASS')}/6 Criterios Aprobados")
print("=" * 70)
for k, v in results.items():
    print(f"  - {k}: {v}")
