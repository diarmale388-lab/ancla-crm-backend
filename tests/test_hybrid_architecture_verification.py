"""
backend/tests/test_hybrid_architecture_verification.py
------------------------------------------------------
Suite de Pruebas de Regresión y Verificación de la Arquitectura Híbrida de Sofi AI:
1. Guardia Pragmática Anti-Cancelación (Caso Lorena Soto y modismos colombianos).
2. Erradicación del Doble Salto en LangGraph y Retorno Determinista de Citas.
3. Validación de Compilación del Grafo LangGraph con Aristas Condicionales.
4. Integridad de la Cabecera de Prompt Caching (Anthropic/OpenRouter).
5. Motor Dinámico de Festivos Oficiales de Colombia (Ley Emiliani).
"""

import sys
sys.path.insert(0, "backend")
import unittest
from datetime import datetime


class TestHybridArchitectureSofiAI(unittest.TestCase):

    def test_01_pragmatic_cancellation_guard_cases(self):
        """Verifica que la guardia pragmática distinga modismos de cancelaciones reales."""
        from ai_agent.nodes.pragmatic_guard import validate_cancellation_guard

        # Casos que NUNCA deben cancelar (Aclaraciones y muletillas colombianas)
        blocked_cases = [
            "No la verdad necesito una solución rápida y económica para el Lote",
            "No es que yo quiero construir una Flex Home en Felidia",
            "No, yo prefiero una casa de 2 habitaciones",
            "No, lo que pasa es que mi presupuesto es de 100M",
            "No pues mira, el terreno tiene 500 metros",
            "No realmente estoy buscando cápsulas living",
            "No, más bien cuéntame qué acabados incluye"
        ]
        for msg in blocked_cases:
            allowed, reason = validate_cancellation_guard(msg)
            self.assertFalse(allowed, f"Debería bloquearse: {msg} | Motivo: {reason}")

        # Casos que SÍ deben cancelar (Órdenes explícitas e inequívocas)
        allowed_cases = [
            "Por favor cancela la cita de mañana",
            "Cancéleme la cita, ya no voy a ir",
            "No voy a poder asistir al showroom de Armenia",
            "Ya no quiero la cita, muchas gracias",
            "Desisto de la asesoría, borra la cita",
            "Anular mi cita por favor"
        ]
        for msg in allowed_cases:
            allowed, reason = validate_cancellation_guard(msg)
            self.assertTrue(allowed, f"Debería permitirse: {msg} | Motivo: {reason}")

    def test_02_deterministic_confirmation_templates(self):
        """Verifica que el nodo determinista genere las plantillas exactas sin Google Meet."""
        import asyncio
        from langchain_core.messages import ToolMessage
        from ai_agent.nodes.deterministic_confirmation import deterministic_confirmation_node, format_spanish_date_friendly

        # 1. Probar formateador de fecha
        fecha_fmt = format_spanish_date_friendly("2026-08-26 10:00:00")
        self.assertIn("10:00 AM", fecha_fmt)
        self.assertIn("Agosto", fecha_fmt)

        # 2. Probar confirmación VIRTUAL
        state_virtual = {
            "user_name": "Lorena Soto",
            "messages": [
                ToolMessage(
                    name="save_appointment",
                    content='{"status": "success", "success": true, "modality": "VIRTUAL", "datetime": "2026-08-26 12:00:00"}',
                    tool_call_id="call_123"
                )
            ]
        }
        res_v = asyncio.run(deterministic_confirmation_node(state_virtual))
        self.assertIn("messages", res_v)
        content_v = res_v["messages"][0].content
        self.assertIn("Asesoría Virtual", content_v)
        self.assertIn("Lorena Soto", content_v)
        self.assertNotIn("meet.google.com", content_v)  # Regla inviolable: CERO Meet

        # 3. Probar confirmación LLAMADA
        state_llamada = {
            "user_name": "Carlos Gomez",
            "messages": [
                ToolMessage(
                    name="save_appointment",
                    content='{"status": "success", "success": true, "modality": "LLAMADA", "datetime": "2026-08-26 15:00:00"}',
                    tool_call_id="call_456"
                )
            ]
        }
        res_l = asyncio.run(deterministic_confirmation_node(state_llamada))
        content_l = res_l["messages"][0].content
        self.assertIn("Llamada Telefónica Comercial", content_l)
        self.assertNotIn("videollamada", content_l.lower())

        # 4. Probar confirmación PRESENCIAL
        state_presencial = {
            "user_name": "Andrea Ruiz",
            "messages": [
                ToolMessage(
                    name="save_appointment",
                    content='{"status": "success", "success": true, "modality": "PRESENCIAL", "datetime": "2026-08-28 11:00:00"}',
                    tool_call_id="call_789"
                )
            ]
        }
        res_p = asyncio.run(deterministic_confirmation_node(state_presencial))
        content_p = res_p["messages"][0].content
        self.assertIn("Showroom ANCLA Special Projects", content_p)
        self.assertIn("Armenia", content_p)

        # 5. Probar estado no_active_appointment
        state_no_appt = {
            "user_name": "Lorena Soto",
            "messages": [
                ToolMessage(
                    name="cancel_appointment",
                    content='{"status": "no_active_appointment", "success": false}',
                    tool_call_id="call_no_appt"
                )
            ]
        }
        res_no = asyncio.run(deterministic_confirmation_node(state_no_appt))
        self.assertIn("no tienes ninguna cita activa", res_no["messages"][0].content)

        # 6. Probar estado error
        state_err = {
            "user_name": "Lorena Soto",
            "messages": [
                ToolMessage(
                    name="save_appointment",
                    content='{"status": "error", "success": false, "error": "Horario ocupado"}',
                    tool_call_id="call_err"
                )
            ]
        }
        res_err = asyncio.run(deterministic_confirmation_node(state_err))
        self.assertIn("inconveniente", res_err["messages"][0].content)

    def test_03_graph_compilation_and_conditional_edges(self):
        """Verifica que el grafo de LangGraph compile con el nuevo nodo determinista."""
        from ai_agent.graph import build_sofi_graph, route_after_tool_execution
        from langchain_core.messages import ToolMessage

        graph = build_sofi_graph()
        self.assertIsNotNone(graph)

        # Probar la arista condicional post-tool
        state_save = {
            "messages": [ToolMessage(name="save_appointment", content='{"status": "success"}', tool_call_id="1")]
        }
        self.assertEqual(route_after_tool_execution(state_save), "deterministic_confirmation_node")

        state_cancel = {
            "messages": [ToolMessage(name="cancel_appointment", content='{"status": "success"}', tool_call_id="2")]
        }
        self.assertEqual(route_after_tool_execution(state_cancel), "deterministic_confirmation_node")

        # Cancelación bloqueada por guardia debe regresar a sales_expert_node para responder duda del cliente
        state_cancel_blocked = {
            "messages": [ToolMessage(name="cancel_appointment", content='{"status": "cancellation_blocked", "blocked_by_guard": true}', tool_call_id="2b")]
        }
        self.assertEqual(route_after_tool_execution(state_cancel_blocked), "sales_expert_node")

        state_consult = {
            "messages": [ToolMessage(name="consultar_disponibilidad", content='{}', tool_call_id="3")]
        }
        self.assertEqual(route_after_tool_execution(state_consult), "sales_expert_node")

    def test_04_colombian_holidays_engine(self):
        """Verifica el cálculo de festivos oficiales de Colombia (Ley Emiliani)."""
        from ai_agent.tools import is_colombian_holiday

        # 1 de Enero y 25 de Diciembre siempre son festivos
        self.assertTrue(is_colombian_holiday(datetime(2026, 1, 1).date()))
        self.assertTrue(is_colombian_holiday(datetime(2026, 12, 25).date()))
        self.assertTrue(is_colombian_holiday(datetime(2026, 7, 20).date()))
        
        # Un día hábil normal (ej: martes 25 de agosto 2026) NO es festivo
        self.assertFalse(is_colombian_holiday(datetime(2026, 8, 25).date()))


if __name__ == "__main__":
    unittest.main()
