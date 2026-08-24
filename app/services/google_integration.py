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

DEFAULT_SERVICE_ACCOUNT_INFO = {
  "type": "service_account",
  "project_id": "ancla-crm",
  "private_key_id": "9d7f78929a031b83a83e56e2e312d91cccb78a0b",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCi7vxcxMV+L5MR\nEdrLF6fEFiaEOV/lG3WivqcgtW9Tf3wzcnHDX6W7TtGf+asjslvA3Or7tKcEBAVC\nJiu5fBLB2iewIMsxzapCOIMzi/G6oPWp1lzkS8JpLE7mkOMqamhZUm1am4e0JPXc\nTHnjn9Um2TeAlHhZUUJxe9aPNE/6IRaa9FNH60SEEkW2eyiKopVT0w98ndLT8NO7\nn1FcjLCcHaljr5FkKjFa0Wdndpjf4Qdq4Kw6q/TpQfwk4PS11GpPQxGs/sGSOM7g\nkuNc4CJNiTGcIkBECKcjxmyd7DagF2Kw/BhdhVVZ+UUX7Q29h/23Ibc3ZlQGVE9j\ntkKYYhjrAgMBAAECggEAAgkwPRNP9m778vT0QdQAJCdn5s1Cuspx8o0lHUSdgsxI\n57Z3Ez5kN0FzLBqpPhWlJ0IVBTBXyYL1WXZZo7eYEmg6VVPFLJ08+RcOSKKBUqT4\ncBCK8gCIvUCw+0xb+LRorMkM/CdaXD1j/XmbjxhFrqnjLPRt+b7vfU4gIbaN7ODg\nD7e1TnXOjrW460U2DW1KfuIZJkJzMJzy9wpcj6MxaYDEmePebS4GdcLyw6AUjVj2\n7TALqDipYlieuTMncAMAWhrtWVu0rpqFmRpf1r7H1Pu80yG75SuKDUg3T37RjTMb\nwfyCS2KQxdyU9NCqeXsX/Eudxb7px5NyxzBFaKAStQKBgQDM6KSL9JGNum4Vm2Tw\n+/RCk06gvOVPHXbV1lLd4M1SQ25FZ/EgnaBcOg1072YFv1njVAxnbkk9fcZbHrCZ\nq5lw+02fvcn4XFQKw6Xoxn0OBzq2lPjdCG+qRKhko+S+Fu523c17qF1lV7DE8Iit\neCIgZYN4T3OoV4Z2ZH/rfOrN3QKBgQDLjw7nUOBqARsA7z+xnxRihA9BJtI6KonB\nIG/erd+9aeqZNBYfqwseEKnF9gDTdFWphykJKXHwaDL8pTEQHfG1XQ/4FPPv6MU5\nBeUGfe87PNgHRsKncatM1Oejd7DsqpdBk6NRLo6E/hO5xQlgka+O6yR+EOeon2Iq\nk+hYA9aJZwKBgGNATHN+AwKjSq8slbgkUivtLiitVmT74JOzPHA8czdlcgQsVJ93\nujTx6ZK6YrBl/yQdkeSHhvJB+dIpC2FjvO78ypyVUT77ebm9Cp+1hN1GoynM/r4R\nWAUhPG+C80kf0mHBDcbXxmVQFE9QMuPTTLRkd0nPMjZYLskp5MwrtZABAoGAb6CE\n2L7WQetXRpzsvdfx0tB+mQjT8kfPgRPrpR6Oeo2xs9AHbdhbYWJb544vB8ZdD3lq\nPHb435AUnc1s6VyyZvWgwzeiSebI+KtN29CFt2N3SA46wp4oBRsf59nEMRSfm7t9\nrRAt4ap/YLk3mjhqIKK8QVG96A93QsgXeuSn6nMCgYEAkv8AdfTJmtMzZnEJ14lW\nlKZ6rKQdGMvd4YqjrMOiA8oWs8NjCwARrxk0hRcXoghpHqOusl1LAuTYactkvCGD\n17R43CDuKKYtbd2TWOlYDQbQieGuozZ0Lm6EF4Xi2OzQ0YT2ePeaOgiwZlETUjEC\nN+wMp9opzQmvjCb0esZUthc=\n-----END PRIVATE KEY-----\n",
  "client_email": "drive-bot-ancla@ancla-crm.iam.gserviceaccount.com",
  "client_id": "114246358670558880936",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/drive-bot-ancla%40ancla-crm.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

def _get_google_credentials():
    """
    Carga las credenciales de Google Service Account con búsqueda multi-entorno:
    1. Variable de entorno GOOGLE_SERVICE_ACCOUNT_JSON
    2. Archivo credentials.json en rutas locales o relativas
    3. Diccionario embebido DEFAULT_SERVICE_ACCOUNT_INFO
    """
    # 1. Variable de entorno
    env_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_CREDENTIALS_JSON")
    if env_json:
        try:
            info = json.loads(env_json) if isinstance(env_json, str) else env_json
            return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            logger.error(f"Error cargando credenciales de Google desde env: {e}")

    # 2. Rutas tentativas en disco
    possible_paths = [
        CREDENTIALS_FILE,
        os.path.join(os.getcwd(), "credentials.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "credentials.json"),
        "credentials.json"
    ]
    for path in possible_paths:
        if os.path.exists(path):
            try:
                return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
            except Exception as e:
                logger.error(f"Error cargando credentials.json desde {path}: {e}")

    # 3. Fallback embebido de producción
    try:
        return service_account.Credentials.from_service_account_info(DEFAULT_SERVICE_ACCOUNT_INFO, scopes=SCOPES)
    except Exception as e:
        logger.error(f"Error cargando credenciales embebidas de Google: {e}")
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


async def create_google_calendar_event(db: Session, appointment: Appointment, contact: Contact) -> tuple[Optional[str], Optional[str]]:
    """
    Crea un evento de Google Calendar real.

    LEY 1 (Contrato Inviolable de Sofi AI) — ERRADICACIÓN TOTAL DE MEET POR CUENTA DE SERVICIO:
    Está PROHIBIDO solicitar o generar enlaces de Google Meet (`conferenceData`) usando la Cuenta
    de Servicio. Únicamente se solicita `conferenceData` cuando existen credenciales OAuth
    PERSONALES de un asesor real (Dirección Comercial conectó su propia cuenta de Google Calendar).
    Mientras Dirección no haya conectado OAuth personal, `google_meet_url` DEBE permanecer
    SIEMPRE `None`, sin importar lo que retorne la API.

    Retorna (event_id, google_meet_url).
    """
    import uuid
    # 1. Determinar el usuario asignado
    user_id = appointment.user_id or (contact.assigned_user_id if contact else None)
    
    creds = None
    if user_id:
        creds = _get_advisor_credentials(db, user_id)

    # Solo se considera "OAuth personal" cuando las credenciales provienen de un asesor real.
    is_personal_oauth = creds is not None

    # 2. Si no hay credenciales de asesor, usar cuenta de servicio (JAMÁS genera Meet, ver LEY 1 arriba)
    if not creds:
        logger.info("No se encontraron credenciales OAuth de asesor. Recurriendo a Cuenta de Servicio (sin generación de Meet).")
        creds = _get_google_credentials()
        
    # Estructura del evento según la Google Calendar API
    start_time = appointment.datetime.isoformat()
    end_time = (appointment.datetime + type(appointment.datetime - appointment.datetime)(hours=1)).isoformat()
    
    request_id = f"meet_{appointment.id}_{uuid.uuid4().hex[:8]}"
    
    attendees_list = []
    if contact.email and "@" in contact.email:
        attendees_list.append({"email": contact.email})
    
    # Agregar correo de Liliana si está configurado
    liliana_email = os.getenv("LILIANA_CALENDAR_EMAIL", "anclagerenciacomercial@gmail.com")
    if liliana_email:
        attendees_list.append({"email": liliana_email})
    
    event_body = {
        "summary": f"Asesoría ANCLA: {contact.first_name or ''} {contact.last_name or ''} ({contact.lot_city or 'Vivienda'})".strip(),
        "description": (
            f"Asesoría ANCLA Special Projects.\n"
            f"Cliente: {contact.first_name or ''} {contact.last_name or ''}\n"
            f"Teléfono: {contact.phone}\n"
            f"Municipio: {contact.lot_city or 'Por definir'}\n"
            f"Notas: {appointment.notes or 'Ninguna'}"
        ),
        "start": {
            "dateTime": start_time,
            "timeZone": "America/Bogota"
        },
        "end": {
            "dateTime": end_time,
            "timeZone": "America/Bogota"
        },
        "attendees": attendees_list,
        "reminders": {
            "useDefault": True
        }
    }

    # LEY 1: conferenceData (Google Meet) SOLO se solicita con OAuth personal real del asesor.
    if is_personal_oauth:
        event_body["conferenceData"] = {
            "createRequest": {
                "requestId": request_id,
                "conferenceSolutionKey": {
                    "type": "hangoutsMeet"
                }
            }
        }

    meet_url = None
    event_id = None

    if creds:
        try:
            service = build('calendar', 'v3', credentials=creds)
            # Intentar crear en el calendario de Liliana si está compartido, o 'primary'
            calendar_id = os.getenv("LILIANA_CALENDAR_ID", "primary")
            event = service.events().insert(
                calendarId=calendar_id,
                body=event_body,
                conferenceDataVersion=1 if is_personal_oauth else 0,
                sendUpdates='all'
            ).execute()
            
            event_id = event.get('id')

            # LEY 1: aunque la API devolviera un enlace, se descarta por completo si no proviene
            # de OAuth personal del asesor (Cuenta de Servicio JAMÁS puede exponer un Meet real).
            if is_personal_oauth:
                meet_url = event.get('hangoutLink')
                if not meet_url and 'conferenceData' in event:
                    entry_points = event['conferenceData'].get('entryPoints', [])
                    for ep in entry_points:
                        if ep.get('entryPointType') == 'video':
                            meet_url = ep.get('uri')
                            break
            else:
                meet_url = None
            
            logger.info(f"Evento real creado en Google Calendar con ID: {event_id} | Meet: {meet_url}")
            print(f"[GOOGLE CALENDAR REAL] Cita agendada exitosamente. Evento ID: {event_id} | Meet: {meet_url}")
        except Exception as e:
            logger.info(f"Google Calendar no autorizado aún o en espera de permisos de Liliana: {e}")

    if not event_id:
        event_id = f"gcal_event_{appointment.id}_{int(datetime.utcnow().timestamp())}"
        event_body["event_id"] = event_id
        event_body["created_at"] = datetime.utcnow().isoformat()
        event_body["status"] = "pending_calendar_auth"
        if meet_url:
            event_body["hangoutLink"] = meet_url

        file_path = os.path.join(CALENDAR_SIM_DIR, f"{event_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(event_body, f, indent=4, ensure_ascii=False)

    # Actualizar appointment en base de datos solo con datos reales
    appointment.google_event_id = event_id
    appointment.google_meet_url = meet_url
    db.commit()

    return event_id, meet_url


async def cancel_google_calendar_event(db: Session, appointment: Appointment) -> bool:
    """
    Cancela (elimina) de forma best-effort el evento real en Google Calendar vinculado a la cita.
    Si el evento era solo una simulación local (sin credenciales conectadas) o si Calendar aún
    no está autorizado, no falla: simplemente no hay nada real que cancelar en Google.
    Retorna True si se eliminó el evento remoto, False en cualquier otro caso (nunca lanza excepción).
    """
    event_id = appointment.google_event_id
    if not event_id or event_id.startswith("gcal_event_"):
        # Evento simulado localmente (Dirección aún no conectó Calendar): nada que cancelar en Google.
        return False

    user_id = appointment.user_id
    creds = _get_advisor_credentials(db, user_id) if user_id else None
    if not creds:
        creds = _get_google_credentials()
    if not creds:
        return False

    try:
        service = build('calendar', 'v3', credentials=creds)
        calendar_id = os.getenv("LILIANA_CALENDAR_ID", "primary")
        service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates='all').execute()
        logger.info(f"Evento de Google Calendar {event_id} cancelado exitosamente.")
        return True
    except Exception as e:
        logger.info(f"No se pudo cancelar el evento remoto {event_id} en Google Calendar (puede ya no existir): {e}")
        return False


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


async def download_file_from_google_drive(file_id: str, db: Session = None) -> Optional[tuple[bytes, str]]:
    """
    Descarga los bytes y el mime_type de un archivo guardado en Google Drive usando OAuth del admin o cuenta de servicio.
    """
    creds = None
    if db:
        oauth_user = db.query(User).filter(User.google_refresh_token.isnot(None)).first()
        if oauth_user:
            creds = _get_advisor_credentials(db, oauth_user.id)
    if not creds:
        from app.database import SessionLocal
        local_db = SessionLocal()
        try:
            oauth_user = local_db.query(User).filter(User.google_refresh_token.isnot(None)).first()
            if oauth_user:
                creds = _get_advisor_credentials(local_db, oauth_user.id)
        finally:
            local_db.close()
    if not creds:
        creds = _get_google_credentials()
    if not creds:
        return None
    try:
        service = build('drive', 'v3', credentials=creds)
        # Obtener metadata para el mimeType
        file_meta = service.files().get(fileId=file_id, fields='mimeType, name', supportsAllDrives=True).execute()
        mime_type = file_meta.get('mimeType', 'image/jpeg')
        
        # Descargar el contenido
        content = service.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
        return content, mime_type
    except Exception as e:
        logger.error(f"Error descargando archivo de Google Drive (ID {file_id}): {e}")
        return None
