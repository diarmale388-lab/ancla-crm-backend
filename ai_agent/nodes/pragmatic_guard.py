"""
ai_agent/nodes/pragmatic_guard.py
---------------------------------
Guardia pragmática en Python para el español colombiano.
Protege contra falsos positivos de cancelación cuando el cliente usa conectores
discursivos enfáticos ("No la verdad...", "No es que...", "No yo necesito...").
"""

import re
from typing import Tuple


def is_explicit_cancellation_intent(text: str) -> bool:
    """
    Evalúa si el texto contiene una orden EXPLÍCITA e INEQUÍVOCA de cancelación o desistimiento.
    """
    if not text:
        return False
    
    t = text.lower().strip()
    
    explicit_cancellation_patterns = [
        r"\bcancela\b",
        r"\bcancelar\b",
        r"\bcancele\b",
        r"\bcancéleme\b",
        r"\bcancélamela\b",
        r"\bcancelame\b",
        r"\bya no quiero\b",
        r"\bya no puedo asistir\b",
        r"\bno voy a ir\b",
        r"\bno puedo ir\b",
        r"\bno voy a poder\b",
        r"\bno puedo asistir\b",
        r"\bno podre asistir\b",
        r"\bno podré asistir\b",
        r"\bno voy a asistir\b",
        r"\bdesisto\b",
        r"\bborra la cita\b",
        r"\banula la cita\b",
        r"\banular\b",
        r"\bno me interesa la cita\b"
    ]
    
    for pattern in explicit_cancellation_patterns:
        if re.search(pattern, t):
            return True
            
    return False


def is_emphatic_colombian_negation(text: str) -> bool:
    """
    Detecta si el mensaje inicia o contiene partículas enfáticas/aclaratorias típicas
    del español colombiano ("No, la verdad...", "No, es que...", "No, yo quiero...").
    """
    if not text:
        return False
        
    t = text.lower().strip()
    
    emphatic_patterns = [
        r"^no\s*,?\s*(la verdad|realmente|lo que pasa|es que|yo|pues|mas bien|más bien|por ahora|mejor)",
        r"^no\s*,?\s*(necesito|quiero|busco|prefiero|tengo|estoy)",
        r"no\s*,?\s*la verdad\s+(necesito|quiero|busco|tengo|prefiero|me gustaria|me gustaría)",
        r"no\s*,?\s*es que\s+(necesito|quiero|busco|tengo|mi presupuesto|el lote)",
        r"no\s*,?\s*lo que pasa es que"
    ]
    
    for pattern in emphatic_patterns:
        if re.search(pattern, t):
            return True
            
    return False


def validate_cancellation_guard(user_message: str) -> Tuple[bool, str]:
    """
    Guardia de doble cerrojo en Python antes de ejecutar cancel_appointment.
    
    Returns:
        (allow_cancellation: bool, reason: str)
    """
    if not user_message:
        return True, "Mensaje vacío - permitiendo flujo estándar"
        
    # 1. Si contiene orden explícita de cancelación -> PERMITIR
    if is_explicit_cancellation_intent(user_message):
        return True, "Orden explícita de cancelación confirmada"
        
    # 2. Si contiene muletilla enfática colombiana y NO orden explícita -> BLOQUEAR
    if is_emphatic_colombian_negation(user_message):
        return False, f"Bloqueo pragmático activado: '{user_message}' es una aclaración de requerimientos, no una orden de cancelación."
        
    # 3. Si no es muletilla pero tampoco orden explícita -> BLOQUEAR por seguridad
    return False, f"Bloqueo preventivo: No se detectó ninguna palabra clave de cancelación explícita en '{user_message}'."
