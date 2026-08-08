import sys
import os
import time
import argparse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

neon_db_url = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_u0jKzE8lWQfb@ep-misty-night-aw10uqbm.c-12.us-east-1.aws.neon.tech/neondb?sslmode=require")
engine = create_engine(neon_db_url)
Session = sessionmaker(bind=engine)

def tail_logs(phone=None, contact_id=None, follow=False, limit=20):
    db = Session()
    
    target_contact_id = contact_id
    if phone and not target_contact_id:
        cleaned_phone = "".join(filter(str.isdigit, str(phone)))
        sql_c = text("SELECT id, first_name, last_name, phone FROM contacts WHERE phone LIKE :ph OR phone LIKE :ph_clean LIMIT 1")
        res_c = db.execute(sql_c, {"ph": f"%{phone}%", "ph_clean": f"%{cleaned_phone}%"}).fetchone()
        if res_c:
            target_contact_id = res_c[0]
            print(f"[FIND] Contacto encontrado: ID {res_c[0]} | {res_c[1]} {res_c[2]} ({res_c[3]})")
        else:
            print(f"[WARNING] No se encontro ningun contacto en la BD con el telefono '{phone}'.")
            return

    last_id = 0
    sql = """
        SELECT a.id, a.trace_id, a.contact_id, a.timestamp, a.source, a.event_type, a.execution_path, a.payload, c.first_name, c.phone
        FROM event_audit_trail a
        LEFT JOIN contacts c ON a.contact_id = c.id
    """
    where_clauses = []
    params = {}

    if target_contact_id:
        where_clauses.append("a.contact_id = :cid")
        params["cid"] = target_contact_id

    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)

    sql += f" ORDER BY a.id DESC LIMIT {limit}"

    res = db.execute(text(sql), params).fetchall()
    print(f"\n================ MAQUINA DE RASTREO AUDIT TRAIL ({len(res)} EVENTOS) ================\n")

    for r in reversed(res):
        last_id = max(last_id, r[0])
        ts = r[3].strftime("%Y-%m-%d %H:%M:%S") if r[3] else "N/A"
        safe_payload = str(r[7]).encode('ascii', errors='backslashreplace').decode('ascii')
        print(f"[{ts}] ID:{r[0]} | TraceID: {r[1]}")
        print(f"  Contacto: ID {r[2]} ({r[8]} - {r[9]})")
        print(f"  Origen (source): {r[4]} | Evento: {r[5]}")
        print(f"  Ruta de Ejecucion: {r[6]}")
        print(f"  Payload: {safe_payload[:180]}")
        print("-" * 75)

    if follow:
        print("\n[LIVE] Inspeccionando en tiempo real (Ctrl+C para salir)...\n")
        try:
            while True:
                time.sleep(2.0)
                db.close()
                db = Session()
                sql_follow = """
                    SELECT a.id, a.trace_id, a.contact_id, a.timestamp, a.source, a.event_type, a.execution_path, a.payload, c.first_name, c.phone
                    FROM event_audit_trail a
                    LEFT JOIN contacts c ON a.contact_id = c.id
                    WHERE a.id > :last_id
                """
                params_f = {"last_id": last_id}
                if target_contact_id:
                    sql_follow += " AND a.contact_id = :cid"
                    params_f["cid"] = target_contact_id
                sql_follow += " ORDER BY a.id ASC"

                new_rows = db.execute(text(sql_follow), params_f).fetchall()
                for r in new_rows:
                    last_id = max(last_id, r[0])
                    ts = r[3].strftime("%Y-%m-%d %H:%M:%S") if r[3] else "N/A"
                    safe_payload = str(r[7]).encode('ascii', errors='backslashreplace').decode('ascii')
                    print(f"[NUEVO EVENTO EN VIVO - {ts}] ID:{r[0]} | TraceID: {r[1]}")
                    print(f"  Contacto: ID {r[2]} ({r[8]} - {r[9]})")
                    print(f"  Origen (source): {r[4]} | Evento: {r[5]}")
                    print(f"  Ruta de Ejecucion: {r[6]}")
                    print(f"  Payload: {safe_payload[:180]}")
                    print("-" * 75)
        except KeyboardInterrupt:
            print("\n[STOP] Rastreo en tiempo real finalizado.")

    db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Máquina de Rastreo de Auditoría en Tiempo Real para Sofi AI.")
    parser.add_argument("--phone", type=str, help="Filtrar eventos por número de teléfono del cliente (ej: 573016261657)")
    parser.add_argument("--contact", type=int, help="Filtrar eventos por ID del contacto (ej: 477)")
    parser.add_argument("--follow", action="store_true", help="Mantener consola abierta escuchando nuevos eventos en tiempo real")
    parser.add_argument("--limit", type=int, default=20, help="Número de eventos pasados a mostrar (default: 20)")
    
    args = parser.parse_args()
    tail_logs(phone=args.phone, contact_id=args.contact, follow=args.follow, limit=args.limit)
