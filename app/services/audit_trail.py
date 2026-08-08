import uuid
import json
import logging
import inspect
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger("audit_trail")

def log_event_audit(
    db: Session,
    source: str,
    event_type: str,
    contact_id: Optional[int] = None,
    trace_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    execution_path: Optional[str] = None
) -> str:
    """
    Registra un evento de auditoría conversacional en la tabla event_audit_trail de Neon DB.
    Retorna el trace_id utilizado.
    """
    if not trace_id:
        trace_id = str(uuid.uuid4())

    if not execution_path:
        caller_frame = inspect.stack()[1]
        filename = caller_frame.filename.replace('\\', '/')
        if 'backend/' in filename:
            filename = filename.split('backend/')[-1]
        execution_path = f"{filename} -> Line {caller_frame.lineno} -> {caller_frame.function}"

    payload_json = json.dumps(payload or {}, ensure_ascii=False)

    try:
        sql = text("""
            INSERT INTO event_audit_trail (trace_id, contact_id, source, event_type, payload, execution_path)
            VALUES (:trace_id, :contact_id, :source, :event_type, :payload, :execution_path)
        """)
        db.execute(sql, {
            "trace_id": trace_id,
            "contact_id": contact_id,
            "source": source,
            "event_type": event_type,
            "payload": payload_json,
            "execution_path": execution_path
        })
        db.commit()
        logger.info(f"[AUDIT TRAIL] TraceID: {trace_id} | Source: {source} | Event: {event_type} | Path: {execution_path}")
    except Exception as e:
        logger.error(f"[AUDIT TRAIL ERROR] No se pudo guardar el evento de auditoría: {e}")
        try:
            db.rollback()
        except Exception:
            pass

    return trace_id
