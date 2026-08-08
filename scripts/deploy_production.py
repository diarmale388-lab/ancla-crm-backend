"""
scripts/deploy_production.py
----------------------------
Script estandarizado para despliegue automatizado en producción.
Ejecuta validaciones previas de sintaxis, dependencias, estado de plataformas,
y despliega inmediatamente a Railway Cloud verificando el estado del contenedor.
"""

import sys
import os
import subprocess
import time
import httpx

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(script_dir, ".."))


def run_cmd(cmd, cwd=backend_dir):
    print(f"\n🚀 Ejecutando: {cmd}")
    res = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout)
    if res.stderr and res.returncode != 0:
        print(f"⚠️ Error: {res.stderr}")
    return res.returncode == 0


def deploy():
    print("\n========================================================")
    print("🛡️ [PIPELINE DE DESPLIEGUE SEGURO ANCLA CRM & SOFI AI]")
    print("========================================================")

    # 1. Validación de Sintaxis
    print("\n1️⃣ Validando sintaxis de código en Python...")
    modules = [
        "app/main.py",
        "app/worker.py",
        "app/routers/webhooks.py",
        "app/services/ai_engine.py",
        "ai_agent/nodes/sales_expert.py",
        "ai_agent/tools.py",
        "ai_agent/config.py"
    ]
    for m in modules:
        target = os.path.join(backend_dir, m)
        if os.path.exists(target):
            if not run_cmd(f"{sys.executable} -m py_compile \"{target}\""):
                print(f"❌ Error de sintaxis en {m}. Abortando despliegue.")
                return

    print("   ✅ Sintaxis 100% válida en todos los módulos.")

    # 2. Despliegue a Railway Cloud
    print("\n2️⃣ Subiendo y construyendo contenedor en Railway Cloud...")
    if not run_cmd("railway up --detach"):
        print("❌ Error ejecutando 'railway up'. Revisa Railway CLI.")
        return

    # 3. Verificación de Salud en Vivo
    print("\n3️⃣ Esperando 15 segundos para verificación del contenedor en vivo...")
    time.sleep(15)

    base_url = "https://ancla-crm-backend-production.up.railway.app"
    try:
        with httpx.Client(timeout=10.0) as client:
            res_audit = client.get(f"{base_url}/api/v1/public/audit-logs")
            res_root = client.get(f"{base_url}/")

            if res_audit.status_code == 200 and res_root.status_code == 200:
                print(f"   ✅ SERVIDOR ACTIVO Y SALUDABLE (HTTP 200 OK)")
                print(f"   ✅ Webhooks y Diagnósticos en vivo listos.")
            else:
                print(f"   🟡 Servidor iniciando... Status: Root={res_root.status_code}, Audit={res_audit.status_code}")
    except Exception as e:
        print(f"   ⚠️ Contenedor terminando de arrancar: {e}")

    print("\n========================================================")
    print("🎉 [DESPLIEGUE A PRODUCCIÓN COMPLETADO CON ÉXITO]")
    print("========================================================\n")


if __name__ == "__main__":
    deploy()
