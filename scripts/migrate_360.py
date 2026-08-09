import os
import sys
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

from app.database import engine
from sqlalchemy import text

def apply_migrations():
    print("🚀 Aplicando migraciones de base de datos para Ficha Técnica 360°...")
    with engine.connect() as conn:
        # 1. Crear tabla advisor_bitacora_notes si no existe
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS advisor_bitacora_notes (
                id SERIAL PRIMARY KEY,
                contact_id INTEGER REFERENCES contacts(id) ON DELETE CASCADE,
                user_id INTEGER,
                author_name VARCHAR(150),
                note_type VARCHAR(50),
                content TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """))

        # 2. Agregar columnas 360 a contacts si no existen
        columns_to_add = [
            ("qualification_level", "VARCHAR(50) DEFAULT 'WARM'"),
            ("commercial_viability", "VARCHAR(50) DEFAULT 'HIGH'"),
            ("has_confirmed_budget", "BOOLEAN DEFAULT TRUE"),
            ("contact_response_status", "VARCHAR(50) DEFAULT 'ANSWERED'"),
            ("quoted_value", "FLOAT DEFAULT 0.0"),
            ("proposal_pdf_url", "VARCHAR(500)"),
            ("proposal_notes", "TEXT")
        ]

        for col_name, col_type in columns_to_add:
            try:
                conn.execute(text(f"ALTER TABLE contacts ADD COLUMN IF NOT EXISTS {col_name} {col_type};"))
                print(f"   ✅ Columna '{col_name}' verificada/añadida.")
            except Exception as e:
                print(f"   ⚠️ {col_name}: {e}")

        conn.commit()
    print("🎉 Migraciones completadas con éxito en la base de datos de producción Neon/Railway!")

if __name__ == "__main__":
    apply_migrations()
