"""
backend/app/services/blackbox_auditor.py
-----------------------------------------
Servicio Centralizado de Auditoría "Caja Negra" para Sofi AI.
Capta, procesa y registra en tiempo real todos los mensajes entrantes,
errores técnicos, tracebacks de excepciones, payloads de Meta API,
modelos de IA utilizados y resoluciones de agendamiento.
"""

import logging
import traceback
import datetime as dt
from typing import Optional, Dict, Any

logger = logging.getLogger("blackbox_auditor")


class BlackBoxAuditor:
    """
    Registrador autónomo de diagnóstico forense para Sofi AI y ANCLA CRM.
    """

    @staticmethod
    def log_event(
        event_type: str,
        description: str,
        contact_id: Optional[int] = None,
        contact_phone: Optional[str] = None,
        contact_name: Optional[str] = None,
        severity: str = "INFO", # INFO, WARNING, CRITICAL, ERROR
        input_payload: Optional[str] = None,
        output_payload: Optional[str] = None,
        error_traceback: Optional[str] = None,
        model_used: Optional[str] = None,
        resolved_status: str = "RESOLVED", # RESOLVED, INVESTIGATING, FAILED
        db: Optional[Any] = None
    ):
        """
        Guarda un registro detallado en la tabla 'ai_blackbox_logs' de Neon PostgreSQL.
        """
        close_db_on_exit = False
        if not db:
            try:
                from app.database import SessionLocal
                db = SessionLocal()
                close_db_on_exit = True
            except Exception as e:
                logger.error(f"Error abriendo sesión DB en BlackBoxAuditor: {e}")
                return

        try:
            from app.models.base import AIBlackBoxLog
            
            full_error = error_traceback
            if not full_error and severity in ["CRITICAL", "ERROR"]:
                full_error = traceback.format_exc()

            log_entry = AIBlackBoxLog(
                contact_id=contact_id,
                contact_phone=contact_phone,
                event_type=event_type,
                severity=severity,
                description=description,
                input_payload=str(input_payload) if input_payload else None,
                output_payload=str(output_payload) if output_payload else None,
                model_used=model_used or "openai/gpt-4o",
                resolved_status=resolved_status,
                created_at=dt.datetime.utcnow()
            )
            db.add(log_entry)
            db.commit()
            logger.info(f"📦 [CAJA NEGRA LOG]: [{event_type}] ({severity}) - {description[:80]}")
        except Exception as err:
            logger.error(f"Fallo guardando evento en Caja Negra: {err}")
        finally:
            if close_db_on_exit and db:
                db.close()


blackbox_auditor = BlackBoxAuditor()
