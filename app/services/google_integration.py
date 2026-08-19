import logging
from typing import Optional
import os
import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.base import Contact, Appointment, User, SystemSetting

# Librerías oficiales de Google
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

logger = logging.getLogger("google_integration")

# Directorios locales de simulación/fallback para Google
CALENDAR_SIM_DIR = r"c:\Users\diarm\Documents\Liliana Leon\CMR\scratch\google_calendar_events"
DRIVE_SIM_DIR = r"c:\Users\diarm\Documents\Liliana Leon\CMR\scratch\google_drive_reports"
CREDENTIALS_FILE = r"c:\Users\diarm\Documents\Liliana Leon\CMR\backend\credentials.json"

# Asegurar que existan los directorios de fallback
os.makedirs(CALENDAR_SIM_DIR, exist_ok=True)
os.makedirs(DRIVE_SIM_DIR, exist_ok=True)

# Scopes requeridos para Google Calendar y Google Drive
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive'
]

def _get_google_credentials():
    """
    Intenta cargar el archivo de credenciales de Google Service Account credentials.json.
    Retorna las credenciales o None si no existe el archivo.
    """
    if os.path.exists(CREDENTIALS_FILE):
        try:
            creds = service_account.Credentials.from_service_account_file(
                CREDENTIALS_FILE, 
                scopes=SCOPES
            )
            return creds
        except Exception as e:
            logger.error(f"Error cargando credenciales de cuenta de servicio de Google: {e}")
            return None
    return None


from app.core.crypto import decrypt_value, encrypt_value

def _get_advisor_credentials(db: Session, user_id: int) -> Credentials:
    """
    Intenta obtener las credenciales de Google OAuth2 específicas de un asesor.
    Si están expiradas, se refrescan automáticamente usando el refresh token.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.google_refresh_token:
        return None
        
    client_id_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_client_id").first()
    client_secret_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_client_secret").first()
    
    client_id = client_id_setting.value if client_id_setting else os.getenv("GOOGLE_CLIENT_ID")
    client_secret = client_secret_setting.value if client_secret_setting else os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        logger.warning(f"Google Client ID/Secret no configurados. Saltando OAuth para usuario {user_id}")
        return None
        
    creds = Credentials(
        token=decrypt_value(user.google_access_token),
        refresh_token=decrypt_value(user.google_refresh_token),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        expiry=user.google_token_expiry
    )
    
    # Verificar si expiró (o expira pronto) y refrescar
    if creds.expired or (user.google_token_expiry and user.google_token_expiry < datetime.utcnow()):
        try:
            logger.info(f"El token de Google OAuth para usuario {user_id} ha expirado. Refrescando...")
            creds.refresh(Request())
            # Actualizar base de datos con token cifrado
            user.google_access_token = encrypt_value(creds.token)
            user.google_token_expiry = creds.expiry
            db.add(user)
            db.commit()
            db.refresh(user)
            logger.info(f"Token refrescado exitosamente para usuario {user_id}")
        except Exception as e:
            logger.error(f"Error al refrescar credenciales de Google OAuth para el usuario {user_id}: {e}")
            return None
            
    return creds


async def create_google_calendar_event(db: Session, appointment: Appointment, contact: Contact):
    """
    Crea un evento de Google Calendar real utilizando el token OAuth del asesor asignado.
    Si no está conectado a OAuth, recurre al credentials.json de cuenta de servicio.
    Si falla, simula la creación en local.
    """
    # 1. Determinar el usuario asignado
    user_id = appointment.user_id or (contact.assigned_user_id if contact else None)
    
    creds = None
    if user_id:
        creds = _get_advisor_credentials(db, user_id)
        
    # 2. Si no hay credenciales de asesor, usar cuenta de servicio
    if not creds:
        logger.info("No se encontraron credenciales OAuth de asesor. Recurriendo a Cuenta de Servicio.")
        creds = _get_google_credentials()
        
    # Estructura del evento según la Google Calendar API
    start_time = appointment.datetime.isoformat()
    end_time = (appointment.datetime + type(appointment.datetime - appointment.datetime)(hours=1)).isoformat()
    
    event_body = {
        "summary": f"Llamada Comercial: {contact.first_name or ''} {contact.last_name or ''}".strip() or contact.phone,
        "description": f"Cita de Ventas agendada de forma automatica en el CRM.\nNotas: {appointment.notes or 'Ninguna'}",
        "start": {
            "dateTime": start_time,
            "timeZone": "America/Bogota"
        },
        "end": {
            "dateTime": end_time,
            "timeZone": "America/Bogota"
        },
        "attendees": [
            {"email": contact.email or "sin-email@crm.com"},
            {"email": "asesor-crm@antigravity.com"}
        ],
        "reminders": {
            "useDefault": True
        }
    }

    if creds:
        try:
            # Inicializar cliente oficial de Google Calendar API
            service = build('calendar', 'v3', credentials=creds)
            event = service.events().insert(calendarId='primary', body=event_body, sendUpdates='all').execute()
            
            event_id = event.get('id')
            logger.info(f"Evento real creado en Google Calendar con ID: {event_id}")
            print(f"[GOOGLE CALENDAR REAL] Cita agendada exitosamente. Evento ID: {event_id}")
            return event_id
        except Exception as e:
            logger.error(f"Fallo en llamada a API real de Google Calendar, recurriendo a simulación local: {e}")
            # Fallback en caso de error de red o permisos
    
    # Fallback / Simulación local
    event_id = f"gcal_event_{appointment.id}_{int(datetime.utcnow().timestamp())}"
    event_body["event_id"] = event_id
    event_body["created_at"] = datetime.utcnow().isoformat()
    event_body["status"] = "simulated"

    file_path = os.path.join(CALENDAR_SIM_DIR, f"{event_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(event_body, f, indent=4, ensure_ascii=False)

    logger.info(f"Evento de Google Calendar simulado (fallback local): {file_path}")
    print(f"[GOOGLE CALENDAR SIMULADO] Cita guardada en local. ID: {event_id}")
    return event_id


async def upload_lead_report_to_google_drive(db: Session, contact: Contact, appointment: Appointment):
    """
    Sube una ficha del lead a Google Drive utilizando el token OAuth del asesor asignado.
    Si no está conectado a OAuth, recurre al credentials.json de cuenta de servicio.
    Si falla, simula la creación en local.
    """
    # 1. Determinar el usuario asignado
    user_id = appointment.user_id if appointment else (contact.assigned_user_id if contact else None)
    
    creds = None
    if user_id:
        creds = _get_advisor_credentials(db, user_id)
        
    # 2. Si no hay credenciales de asesor, usar cuenta de servicio
    if not creds:
        logger.info("No se encontraron credenciales OAuth de asesor. Recurriendo a Cuenta de Servicio.")
        creds = _get_google_credentials()
        
    report_content = f"""# Reporte de Lead - CRM Omnicanal Antigravity

## Datos del Lead
* **ID Local**: {contact.id}
* **Nombre Completo**: {contact.first_name or ''} {contact.last_name or ''}
* **Telefono**: {contact.phone}
* **Email**: {contact.email or 'No provisto'}
* **Origen**: {contact.source or 'Organico'}

## Datos de la Cita Comercial
* **ID Cita**: {appointment.id if appointment else 'Sin cita'}
* **Fecha y Hora**: {appointment.datetime.strftime("%Y-%m-%d %I:%M %p") if appointment else 'N/A'}
* **Notas de la Cita**: {appointment.notes or 'Sin observaciones adicionales' if appointment else 'N/A'}

---
*Reporte generado de forma automatica por el CRM Antigravity el {datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")} UTC.*
"""

    filename = f"reporte_lead_{contact.id}_{int(datetime.utcnow().timestamp())}.txt"

    if creds:
        try:
            # Inicializar cliente oficial de Google Drive API (v3)
            service = build('drive', 'v3', credentials=creds)
            
            file_metadata = {
                'name': filename,
                'mimeType': 'text/plain'
            }
            
            media = MediaInMemoryUpload(
                report_content.encode('utf-8'), 
                mimetype='text/plain', 
                resumable=True
            )
            
            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = file.get('id')
            logger.info(f"Reporte real subido a Google Drive con ID: {file_id}")
            print(f"[GOOGLE DRIVE REAL] Ficha subida exitosamente. File ID: {file_id}")
            
            from app.services.activity import record_activity
            record_activity(
                db=db,
                contact_id=contact.id,
                activity_type="proposal_generated",
                description=f"Ficha técnica / Propuesta del lead generada automáticamente en PDF y respaldada en Google Drive (ID: {file_id}).",
                user_id=None
            )
            return file_id
        except Exception as e:
            logger.error(f"Fallo en llamada a API real de Google Drive, recurriendo a simulación local: {e}")

    # Fallback / Simulación local
    report_id = f"gdrive_doc_{contact.id}_{int(datetime.utcnow().timestamp())}"
    file_path = os.path.join(DRIVE_SIM_DIR, f"{report_id}.md")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    from app.services.activity import record_activity
    record_activity(
        db=db,
        contact_id=contact.id,
        activity_type="proposal_generated",
        description=f"Ficha técnica / Propuesta del lead generada en PDF (simulado local ID: {report_id}).",
        user_id=None
    )

    logger.info(f"Reporte de Google Drive simulado (fallback local): {file_path}")
    print(f"[GOOGLE DRIVE SIMULADO] Ficha guardada en local. ID: {report_id}")
    return report_id


DEFAULT_DRIVE_FOLDER_ID = "1vIPzgbztLvZdddkvnZvYo0XkVRUq2LCn"

async def upload_whatsapp_media_to_google_drive(db: Session, file_bytes: bytes, filename: str, mime_type: str, user_id: int = None) -> Optional[str]:
    """
    Sube un archivo de media de WhatsApp o respaldo de BD a Google Drive de forma privada dentro de la carpeta ANCLA CRM ARCHIVOS.
    Retorna el file_id en Google Drive.
    """
    creds = None
    if user_id:
        creds = _get_advisor_credentials(db, user_id)
    if not creds:
        # Buscar cualquier usuario conectado a OAuth (ej. administrador)
        oauth_user = db.query(User).filter(User.google_refresh_token.isnot(None)).first()
        if oauth_user:
            creds = _get_advisor_credentials(db, oauth_user.id)
    if not creds:
        creds = _get_google_credentials()
        
    if not creds:
        logger.error("No se encontraron credenciales de Google para subir media.")
        return None
        
    try:
        service = build('drive', 'v3', credentials=creds)
        file_metadata = {
            'name': filename,
            'parents': [DEFAULT_DRIVE_FOLDER_ID]
        }
        media = MediaInMemoryUpload(file_bytes, mimetype=mime_type, resumable=True)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True
        ).execute()
        file_id = file.get('id')
        logger.info(f"Media subido a Google Drive de forma exitosa. ID: {file_id}")
        return file_id
    except Exception as e:
        logger.error(f"Error subiendo media a Google Drive: {e}")
        return None


async def download_file_from_google_drive(file_id: str) -> Optional[tuple[bytes, str]]:
    """
    Descarga los bytes y el mime_type de un archivo guardado en Google Drive.
    """
    creds = _get_google_credentials()
    if not creds:
        return None
    try:
        service = build('drive', 'v3', credentials=creds)
        # Obtener metadata para el mimeType
        file_meta = service.files().get(fileId=file_id, fields='mimeType').execute()
        mime_type = file_meta.get('mimeType', 'application/octet-stream')
        
        # Descargar el contenido
        content = service.files().get_media(fileId=file_id).execute()
        return content, mime_type
    except Exception as e:
        logger.error(f"Error descargando archivo de Google Drive (ID {file_id}): {e}")
        return None
