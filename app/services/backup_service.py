import logging
import json
import gzip
import datetime
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from typing import Optional

from app.services.google_integration import upload_whatsapp_media_to_google_drive
from app.services.activity import record_activity

logger = logging.getLogger("backup_service")

def generate_database_backup_json(db: Session) -> bytes:
    """
    Serializa dinámicamente todas las tablas de la base de datos a un objeto JSON
    y lo comprime con gzip en memoria.
    """
    backup_data = {}
    inspector = inspect(db.bind)
    
    # Obtener nombres de todas las tablas existentes en la BD
    for table_name in inspector.get_table_names():
        # Consultar todos los registros de forma genérica
        result = db.execute(text(f"SELECT * FROM {table_name}"))
        columns = list(result.keys())
        
        rows = []
        for r in result:
            row_dict = {}
            for col in columns:
                # Obtener el valor por el índice del nombre de columna
                val = r[columns.index(col)]
                if isinstance(val, (datetime.datetime, datetime.date)):
                    row_dict[col] = val.isoformat()
                elif isinstance(val, datetime.time):
                    row_dict[col] = val.strftime("%H:%M:%S")
                elif hasattr(val, '__dict__'):
                    # En caso de objetos complejos no primitivos
                    row_dict[col] = str(val)
                else:
                    row_dict[col] = val
            rows.append(row_dict)
            
        backup_data[table_name] = rows
        
    # Convertir diccionario a JSON String
    json_str = json.dumps(backup_data, ensure_ascii=False, indent=2)
    # Comprimir usando gzip
    compressed_data = gzip.compress(json_str.encode('utf-8'))
    return compressed_data

async def run_database_backup_to_drive(db: Session) -> Optional[str]:
    """
    Ejecuta el volcado de base de datos comprimido y lo sube a tu cuenta de Google Drive corporativa.
    Retorna el ID del archivo subido en Google Drive.
    """
    try:
        logger.info("Iniciando generación de copia de seguridad de la base de datos...")
        compressed_bytes = generate_database_backup_json(db)
        
        # Generar nombre del archivo con timestamp
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H%M%S")
        filename = f"crm_backup_{timestamp}.json.gz"
        mime_type = "application/gzip"
        
        logger.info(f"Copia de seguridad generada con éxito ({len(compressed_bytes)} bytes comprimidos). Subiendo a Google Drive...")
        
        # Subir usando la API de Google Drive
        drive_file_id = await upload_whatsapp_media_to_google_drive(
            db=db,
            file_bytes=compressed_bytes,
            filename=filename,
            mime_type=mime_type
        )
        
        if drive_file_id:
            logger.info(f"Copia de seguridad subida exitosamente a Google Drive. ID: {drive_file_id}")
            # Registrar actividad del sistema
            record_activity(
                db=db,
                contact_id=None,
                activity_type="system_backup",
                description=f"Copia de seguridad del sistema generada y subida exitosamente a Google Drive. Archivo: '{filename}' (ID: {drive_file_id}).",
                user_id=None
            )
            return drive_file_id
        else:
            logger.error("Fallo al subir el archivo de copia de seguridad a Google Drive.")
            return None
            
    except Exception as e:
        logger.error(f"Excepción al ejecutar la copia de seguridad a Google Drive: {e}")
        return None
