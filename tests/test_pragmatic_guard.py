import sys
sys.path.insert(0, "backend")
from ai_agent.nodes.pragmatic_guard import validate_cancellation_guard

TESTS = [
    ("No la verdad necesito una solución rápida y económica para el Lote", False),
    ("No es que yo quiero construir una Flex Home en Felidia", False),
    ("No, yo prefiero una de 2 habitaciones", False),
    ("Por favor cancela la cita de mañana", True),
    ("Cancéleme la cita, ya no voy a ir", True),
    ("No voy a poder asistir al showroom", True),
    ("Ya no quiero la cita, gracias", True),
    ("No, lo que pasa es que mi presupuesto es de 100M", False)
]

for text, expected in TESTS:
    allowed, reason = validate_cancellation_guard(text)
    assert allowed == expected, f"FAILED: {text} -> Got {allowed}, Expected {expected}"
    print(f"[PASS] \"{text[:45]}...\" -> Allowed: {allowed}")

print("ALL PRAGMATIC GUARD TESTS PASSED 100%!")
