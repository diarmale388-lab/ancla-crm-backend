import os
import sys
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

from app.database import engine
from sqlalchemy import text

def apply_bitacora_migrations():
    print("🚀 Aplicando migración de la Bitácora Comercial Pro 360°...")
    with engine.connect() as conn:
        columns_to_add = [
            ("call_result", "VARCHAR(100)"),
            ("construction_timeline", "VARCHAR(100)"),
            ("detected_objection", "VARCHAR(100)"),
            ("next_action", "VARCHAR(100)"),
            ("next_action_date", "VARCHAR(100)")
        ]

        for col_name, col_type in columns_to_add:
            try:
                conn.execute(text(f"ALTER TABLE advisor_bitacora_notes ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                print(f"   ✅ Columna '{col_name}' añadida/verificada en advisor_bitacora_notes.")
            except Exception as e:
                print(f"   ⚠️ {col_name}: {e}")

        conn.commit()
    print("🎉 Migración de Bitácora Pro completada en base de datos de producción Neon/Railway!")

if __name__ == "__main__":
    apply_bitacora_migrations()
