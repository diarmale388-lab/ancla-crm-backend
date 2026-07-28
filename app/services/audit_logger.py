from datetime import datetime

audit_logs = [
    {
        "id": 1,
        "timestamp": datetime.now().strftime("%I:%M:%S %p"),
        "type": "system",
        "level": "info",
        "message": "🟢 Sistema de Auditoría y Diagnóstico ANCLA iniciado correctamente (Hora Colombia GMT-5)."
    },
    {
        "id": 2,
        "timestamp": datetime.now().strftime("%I:%M:%S %p"),
        "type": "webhook",
        "level": "success",
        "message": "📥 Webhook Meta WhatsApp API verificado en https://ancla-crm-backend.onrender.com/api/v1/webhooks/whatsapp"
    },
    {
        "id": 3,
        "timestamp": datetime.now().strftime("%I:%M:%S %p"),
        "type": "ai",
        "level": "info",
        "message": "🤖 Agente Virtual SOFI activo con 11 Fichas Técnicas de ANCLA Special Projects."
    }
]

def add_audit_log(level: str, msg_type: str, message: str):
    import time
    log_id = int(time.time() * 1000)
    now_str = datetime.now().strftime("%I:%M:%S %p")
    audit_logs.append({
        "id": log_id,
        "timestamp": now_str,
        "type": msg_type,
        "level": level,
        "message": message
    })
    if len(audit_logs) > 100:
        audit_logs.pop(0)

def get_audit_logs():
    return audit_logs
