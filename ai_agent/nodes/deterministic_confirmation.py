"""
ai_agent/nodes/deterministic_confirmation.py
---------------------------------------------
Nodo determinista en Python para LangGraph.
Emite respuestas de confirmación canónicas oficiales tras la ejecución de herramientas
(save_appointment, cancel_appointment) erradicando la segunda llamada al LLM
(ahorro del 100% de tokens de síntesis y 3-4 segundos de latencia).
"""

import json
from typing import Dict, Any
from langchain_core.messages import AIMessage
from ai_agent.state import AgentState


def format_spanish_date_friendly(dt_iso: str) -> str:
    """Convierte una fecha ISO (ej: 2026-08-26 10:00:00) a formato amigable en español."""
    if not dt_iso:
        return "la fecha acordada"
    try:
        from datetime import datetime
        # Parse ISO or standard string
        dt_str = str(dt_iso).replace("T", " ")
        if len(dt_str) >= 16:
            dt = datetime.strptime(dt_str[:16], "%Y-%m-%d %H:%M")
        else:
            return dt_iso
            
        meses = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
        ]
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        
        dia_nom = dias[dt.weekday()]
        mes_nom = meses[dt.month - 1]
        hora_fmt = dt.strftime("%I:%M %p").lstrip("0")
        
        return f"{dia_nom} {dt.day} de {mes_nom} a las {hora_fmt}"
    except Exception:
        return dt_iso


async def deterministic_confirmation_node(state: AgentState) -> Dict[str, Any]:
    """
    Lee el resultado de la última herramienta ejecutada en el grafo y genera
    el mensaje final oficial de confirmación en Python puro sin invocar al LLM.
    """
    messages = state.get("messages", [])
    user_name = (state.get("user_name") or "").strip()
    name_display = f"**{user_name}**" if user_name else ""
    
    # Buscar el último ToolMessage
    last_tool_msg = None
    for m in reversed(messages):
        if getattr(m, "type", "") == "tool" or m.__class__.__name__ == "ToolMessage":
            last_tool_msg = m
            break
            
    if not last_tool_msg:
        return {}
        
    tool_name = getattr(last_tool_msg, "name", "")
    content_raw = getattr(last_tool_msg, "content", "")
    
    try:
        data = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except Exception:
        data = {"raw": content_raw}
        
    tool_status = data.get("status", "")
    modality = str(data.get("modality", "VIRTUAL")).upper()
    scheduled_at = data.get("datetime") or data.get("scheduled_at") or ""
    fecha_legible = format_spanish_date_friendly(scheduled_at)
    
    # ─────────────────────────────────────────────────────────────
    # CASO 1: save_appointment
    # ─────────────────────────────────────────────────────────────
    if tool_name == "save_appointment":
        if tool_status == "already_booked" or data.get("already_booked"):
            greeting = f" {name_display}" if name_display else ""
            msg = (
                f"¡Hola{greeting}! 😊 Te confirmo que tu cita ya se encuentra programada y confirmada en nuestra "
                f"agenda para el **{fecha_legible}**. Estaremos muy atentos para atenderte. Si tienes alguna duda "
                f"previa, ¡con gusto te ayudo! 🏡✨"
            )
            return {"messages": [AIMessage(content=msg)]}
            
        if tool_status == "success" or data.get("success"):
            greeting = f"{name_display}, tu" if name_display else "Tu"
            
            if modality == "LLAMADA":
                msg = (
                    f"¡Tu llamada ha sido confirmada! 😊\n\n"
                    f"{greeting} **Llamada Telefónica Comercial** está programada para el **{fecha_legible}**.\n\n"
                    f"📞 **Detalles de la atención:**\n"
                    f"Nuestro equipo de expertos te llamará puntualmente a este número para brindarte toda la información técnica y cotización de tu proyecto de casa modular. ¡Nos comunicamos pronto! 🏡✨"
                )
            elif modality == "PRESENCIAL":
                msg = (
                    f"¡Tu visita al Showroom ha sido confirmada! 😊\n\n"
                    f"{greeting} **Visita Presencial** está programada para el **{fecha_legible}**.\n\n"
                    f"📍 **Ubicación:**\n"
                    f"Showroom ANCLA Special Projects — Avenida Centenario (frente a Pan y Miel), Armenia, Quindío.\n"
                    f"🚗 Parqueadero privado y gratuito disponible.\n"
                    f"🌐 Waze / Maps: https://waze.com/ul/hd36qf4277\n\n"
                    f"¡Te esperamos con los brazos abiertos para conocer nuestros modelos en vivo! 🏡✨"
                )
            else:  # VIRTUAL (default)
                msg = (
                    f"¡Tu cita ha sido confirmada! 😊\n\n"
                    f"{greeting} **Asesoría Virtual** está programada para el **{fecha_legible}**.\n\n"
                    f"📍 **En esta sesión nuestro equipo te presentará en pantalla:**\n"
                    f"1. Los planos y distribución arquitectónica del modelo que elijas (Flex Home o Cápsulas Living).\n"
                    f"2. Renders y fotos reales de los acabados interiores.\n"
                    f"3. La cotización personalizada y detallada puesta directamente en tu lote.\n\n"
                    f"📲 **Modalidad:** Asesoría Virtual (Nuestro equipo se comunicará contigo puntualmente por este medio para iniciar la videollamada). ¡Nos vemos pronto! 🏡✨"
                )
            return {"messages": [AIMessage(content=msg)]}
            
    # ─────────────────────────────────────────────────────────────
    # CASO 2: cancel_appointment
    # ─────────────────────────────────────────────────────────────
    elif tool_name == "cancel_appointment":
        if tool_status == "cancellation_blocked" or data.get("blocked_by_guard"):
            # Si fue bloqueada por guardia, dejamos que el LLM asesore o devolvemos mensaje cálido
            msg = (
                f"¡Con gusto! Cuentas con nosotros para revisar la mejor alternativa para tu lote y presupuesto. "
                f"Tu cita sigue activa para que nuestros especialistas te presenten las opciones más eficientes. ¿Deseas consultar algún detalle específico?"
            )
            return {"messages": [AIMessage(content=msg)]}
            
        if tool_status == "success" or data.get("success"):
            greeting = f" {name_display}" if name_display else ""
            msg = (
                f"¡Entendido{greeting}! 🙌 Tu cita para el **{fecha_legible}** ha sido cancelada exitosamente en nuestra agenda. "
                f"Si más adelante deseas retomar tu proyecto de casa modular o conocer nuestros modelos, con todo gusto estaremos "
                f"disponibles por aquí. ¡Que tengas un excelente día! 🏡✨"
            )
            return {"messages": [AIMessage(content=msg)]}
            
    return {}
