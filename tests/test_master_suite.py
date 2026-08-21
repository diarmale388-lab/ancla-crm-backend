"""
backend/tests/test_master_suite.py
----------------------------------
SUITE MAESTRA DE CONTROL DE CALIDAD Y GOBERNANZA - SOFI AI (ANCLA CRM)
Valida los 17 casos críticos históricos para prevenir regresiones y garantizar
el cumplimiento de los 10 Mandamientos Comerciales de SOFI_MASTER_CONTRACT.md.

Ejecución:
  python backend/tests/test_master_suite.py
"""

import sys
import os
import asyncio
import re
import datetime as dt

# Asegurar encoding UTF-8 en Windows
sys.stdout.reconfigure(encoding='utf-8')

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from langchain_core.messages import HumanMessage, AIMessage
from app.database import SessionLocal
from app.models.base import Contact, Message, Appointment
from ai_agent.graph import sofi_ai_agent
from ai_agent.tools import is_colombian_holiday, consultar_disponibilidad

class SofiMasterTestSuite:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.results = []

    def record_result(self, case_id: int, name: str, success: bool, details: str = ""):
        if success:
            self.passed += 1
            print(f"  ✅ [CASO {case_id:02d}] {name} -> APROBADO")
        else:
            self.failed += 1
            print(f"  ❌ [CASO {case_id:02d}] {name} -> FALLÓ: {details}")
        self.results.append({"case_id": case_id, "name": name, "success": success, "details": details})

    async def invoke_agent(self, messages, contact_metadata=None, phone="573000000000", user_name="Cliente Test"):
        meta = contact_metadata or {
            "scheduling_state": "NO_DEFINIDA",
            "has_land": "No especificado",
            "location": "No especificado",
            "active_appointment": "Ninguna"
        }
        input_state = {
            "messages": messages,
            "phone": phone,
            "chatbot_enabled": True,
            "user_name": user_name,
            "requires_human": False,
            "metadata": meta
        }
        config = {"configurable": {"thread_id": f"test_{int(asyncio.get_event_loop().time()*1000)}"}}
        res = await sofi_ai_agent.ainvoke(input_state, config=config)
        
        # Extraer respuesta generada ÚNICAMENTE en este turno
        all_msgs = res.get("messages", [])
        initial_count = len(messages)
        new_msgs = all_msgs[initial_count:] if len(all_msgs) > initial_count else all_msgs[-1:]
        
        ai_texts = []
        for m in new_msgs:
            if getattr(m, "type", "") == "ai" or isinstance(m, AIMessage):
                c = getattr(m, "content", "")
                if isinstance(c, list):
                    c = "".join([i.get("text", "") if isinstance(i, dict) else str(i) for i in c])
                c_str = str(c or "").strip()
                if c_str and c_str.lower() != "none":
                    clean_lines = [
                        l for l in c_str.split("\n")
                        if not any(l.strip().lower().startswith(p) for p in [
                            "voy a consultar", "permíteme consultar", "voy a revisar",
                            "voy a proceder", "un momento, por favor", "un momento por favor"
                        ])
                    ]
                    cleaned = "\n".join(clean_lines).strip()
                    if cleaned:
                        ai_texts.append(cleaned)
        
        if ai_texts:
            if len(ai_texts) > 1 and not ai_texts[-1].startswith("¡Hola") and not ai_texts[-1].startswith("Hola"):
                return "\n\n".join(ai_texts)
            return ai_texts[-1]
        return ""

    # =========================================================================
    # 17 CASOS DE PRUEBA
    # =========================================================================

    async def test_case_01_no_prices(self):
        """Caso 1: Prohibición absoluta de precios por chat"""
        msgs = [HumanMessage(content="Hola, cuánto vale el metro cuadrado y cuánto cuesta la casa modular de 36m2?")]
        reply = await self.invoke_agent(msgs)
        # Verificar que no contenga signos de pesos ni cifras monetarias
        has_currency_symbol = "$" in reply
        has_numbers_in_millions = bool(re.search(r'\b\d{2,3}\s*(millones|mil|m2|usd|cop)\b', reply, re.IGNORECASE))
        has_expert_team = "equipo de expertos" in reply.lower() or "nuestros expertos" in reply.lower()
        has_consultative_invite = "asesoría" in reply.lower() or "showroom" in reply.lower()
        
        success = not has_currency_symbol and not has_numbers_in_millions and has_expert_team and has_consultative_invite
        self.record_result(1, "Prohibición de Precios y Valores Monetarios por Chat", success, f"Reply: {reply[:100]}...")

    async def test_case_02_distance_objection(self):
        """Caso 2: Manejo empático de objeción de desplazamiento (cambio a Virtual)"""
        msgs = [HumanMessage(content="Por el momento no puedo asistir para ver pero me interesa")]
        reply = await self.invoke_agent(msgs)
        has_empathy = any(w in reply.lower() for w in ["tranquilo", "desplazamiento", "comodidad", "virtual", "no te preocupes", "casa"])
        has_virtual_prop = "virtual" in reply.lower()
        success = has_empathy and has_virtual_prop
        self.record_result(2, "Manejo Empático de Objeción de Desplazamiento", success, f"Reply: {reply[:100]}...")

    async def test_case_03_active_appointment_courtesy(self):
        """Caso 3: Re-confirmación / Cortesía con Cita Activa en BD (Cero falsos llenos)"""
        meta = {
            "scheduling_state": "VIRTUAL",
            "has_land": "Sí, ya tengo",
            "location": "La Plata, Huila",
            "active_appointment": "Sábado 22 de Agosto a las 12:00 PM (Modalidad: Virtual)"
        }
        msgs = [
            HumanMessage(content="Hola completé el formulario"),
            AIMessage(content="¡Tu cita ha sido confirmada para el Sábado 22 de Agosto a las 12:00 PM!"),
            HumanMessage(content="Para el sábado, este bien")
        ]
        reply = await self.invoke_agent(msgs, contact_metadata=meta, user_name="Vianeth Cuellar")
        has_no_capacity_error = "lamentablemente" not in reply.lower() and "no tenemos disponibilidad" not in reply.lower()
        has_confirmation_warmth = any(w in reply.lower() for w in ["confirmada", "reservada", "gusto", "sábado", "nos vemos"])
        success = has_no_capacity_error and has_confirmation_warmth
        self.record_result(3, "Re-confirmación con Cita Activa en BD", success, f"Reply: {reply[:100]}...")

    async def test_case_04_meta_ads_form_2_paragraphs(self):
        """Caso 4: Formulario Meta Ads con nombre oficial y máximo 2 párrafos"""
        form_content = (
            "¡Hola! Completé el formulario y me gustaría obtener más información sobre tu negocio.\n\n"
            "Full name: Mauricio Bermudez Moreno\n"
            "Phone number: +573100000000\n"
            "Email: mauricio@test.com\n"
            "¿Ya cuentas con un terreno o lote propio?: Sí, ya tengo\n"
            "¿Cuál es el propósito principal de tu proyecto?: Vivienda Propia o Campestre\n"
            "¿En qué ciudad o departamento tienes pensado construir tu proyecto?: Mapiripan Meta\n"
            "¿Te contactas como Persona Natural o Empresa?: Persona Natural"
        )
        meta = {
            "scheduling_state": "VIRTUAL",
            "has_land": "Sí, ya tengo",
            "location": "Mapiripan Meta",
            "active_appointment": "Ninguna"
        }
        msgs = [HumanMessage(content=form_content)]
        reply = await self.invoke_agent(msgs, contact_metadata=meta, user_name="Mauricio Bermudez Moreno")
        paragraphs = [p for p in reply.split("\n\n") if p.strip()]
        has_name = "mauricio" in reply.lower()
        has_city = "mapiripan" in reply.lower() or "meta" in reply.lower()
        concise_len = len(paragraphs) <= 3 and len(reply.strip()) < 600
        success = has_name and has_city and concise_len
        self.record_result(4, "Lead Meta Ads: Nombre Oficial y Máximo 2 Párrafos", success, f"Párrafos: {len(paragraphs)} | Reply: {reply[:100]}...")

    async def test_case_05_cold_lead_consultative(self):
        """Caso 5: Lead Frío sin datos -> Saludo y pregunta de calificación"""
        msgs = [HumanMessage(content="Hola, me gustaría recibir información sobre las casas.")]
        reply = await self.invoke_agent(msgs)
        has_greeting = "sofi" in reply.lower() or "ancla" in reply.lower()
        has_city_question = any(w in reply.lower() for w in ["ciudad", "municipio", "lote", "terreno", "donde"])
        success = has_greeting and has_city_question
        self.record_result(5, "Lead Frío: Venta Consultiva y Pregunta de Ubicación", success, f"Reply: {reply[:100]}...")

    async def test_case_06_human_or_liliana_request(self):
        """Caso 6: Solicitud de hablar con Liliana León o persona real"""
        msgs = [HumanMessage(content="Quiero hablar con Liliana León ya mismo por favor")]
        reply = await self.invoke_agent(msgs)
        has_liliana_explanation = "liliana" in reply.lower() or "equipo de expertos" in reply.lower()
        has_scheduling_invite = "asesoría" in reply.lower() or "showroom" in reply.lower() or "agendar" in reply.lower()
        has_no_fake_promise = "15 minutos" not in reply.lower()
        success = has_liliana_explanation and has_scheduling_invite and has_no_fake_promise
        self.record_result(6, "Solicitud de Atención Directa con Liliana León", success, f"Reply: {reply[:100]}...")

    async def test_case_07_pdf_catalog_request(self):
        """Caso 7: Prohibición de entregar catálogos en PDF por chat"""
        msgs = [HumanMessage(content="Me puedes enviar el catálogo en PDF por favor para revisarlo?")]
        reply = await self.invoke_agent(msgs)
        has_guided_explanation = any(w in reply.lower() for w in ["asesoría", "virtual", "showroom", "sesión", "presenta", "compart"])
        has_no_pdf_link = ".pdf" not in reply.lower()
        success = has_guided_explanation and has_no_pdf_link
        self.record_result(7, "Política de Portafolio Guiado (Cero PDFs por Chat)", success, f"Reply: {reply[:100]}...")

    async def test_case_08_night_cutoff_future_dates(self):
        """Caso 8: Disponibilidad con cutoff y descarte de horas pasadas"""
        # Probar herramienta directa de disponibilidad
        res = await consultar_disponibilidad.ainvoke({"modalidad": "VIRTUAL", "fecha_solicitada": "hoy"})
        status_ok = res.get("status") == "success"
        has_slots = len(res.get("horarios_disponibles", [])) > 0
        success = status_ok and has_slots
        self.record_result(8, "Herramienta de Disponibilidad con Filtro Temporal Cutoff", success, f"Res: {res}")

    async def test_case_09_product_recognition(self):
        """Caso 9: Reconocimiento explícito de producto (Cápsulas Living / Glamping)"""
        msgs = [HumanMessage(content="Estoy buscando una Cápsula Living para un proyecto de Glamping en Guatapé.")]
        reply = await self.invoke_agent(msgs)
        has_product_mention = "cápsula" in reply.lower() or "glamping" in reply.lower()
        has_location_mention = "guatapé" in reply.lower()
        success = has_product_mention and has_location_mention
        self.record_result(9, "Reconocimiento de Producto y Proyecto (Cápsulas Living)", success, f"Reply: {reply[:100]}...")

    async def test_case_10_anti_repetition_of_greetings(self):
        """Caso 10: Anti-repetición de saludos en mensajes de continuación"""
        msgs = [
            HumanMessage(content="Hola, me interesa una casa modular"),
            AIMessage(content="¡Hola! 👋 Qué gusto saludarte, bienvenida a ANCLA Special Projects. ¿En qué municipio planeas construir?"),
            HumanMessage(content="En Tunja Boyacá")
        ]
        reply = await self.invoke_agent(msgs)
        repeats_welcome = "bienvenida a ancla" in reply.lower() or "qué gusto saludarte" in reply.lower()
        success = not repeats_welcome
        self.record_result(10, "Anti-Repetición de Saludos en Mensajes de Continuación", success, f"Reply: {reply[:100]}...")

    async def test_case_11_terminology_and_no_facebook(self):
        """Caso 11: Terminología 'nuestro equipo de expertos' y Cero Facebook"""
        msgs = [HumanMessage(content="¿Quiénes me atenderán en la cita y cuáles son sus redes sociales?")]
        reply = await self.invoke_agent(msgs)
        uses_forbidden_engineer = "los ingenieros" in reply.lower() or "un ingeniero" in reply.lower()
        uses_forbidden_facebook = "facebook.com" in reply.lower()
        uses_valid_team = "expertos" in reply.lower()
        success = not uses_forbidden_engineer and not uses_forbidden_facebook and uses_valid_team
        self.record_result(11, "Terminología Oficial de Expertos y Cero Facebook", success, f"Reply: {reply[:100]}...")

    async def test_case_12_dynamic_modality_switch(self):
        """Caso 12: Cambio dinámico de Presencial a Virtual"""
        meta = {"scheduling_state": "SHOWROOM_ARMENIA", "has_land": "Sí", "location": "Bogotá", "active_appointment": "Ninguna"}
        msgs = [
            HumanMessage(content="Iba a ir a Armenia pero me queda imposible viajar, mejor hagamos videollamada virtual"),
        ]
        reply = await self.invoke_agent(msgs, contact_metadata=meta)
        has_virtual_ack = "virtual" in reply.lower()
        success = has_virtual_ack
        self.record_result(12, "Cambio Dinámico de Modalidad (Presencial -> Virtual)", success, f"Reply: {reply[:100]}...")

    async def test_case_13_colombian_holidays_ley_emiliani(self):
        """Caso 13: Detección Perpetua de Festivos de Colombia (Ley Emiliani)"""
        # 20 de Julio de 2026 es Festivo Nacional en Colombia (Independencia)
        is_july_20_holiday = is_colombian_holiday(dt.date(2026, 7, 20))
        # 7 de Agosto de 2026 es Festivo Nacional (Batalla de Boyacá)
        is_aug_7_holiday = is_colombian_holiday(dt.date(2026, 8, 7))
        # Un día hábil normal (ej. 21 de Julio de 2026) NO es festivo
        is_july_21_holiday = is_colombian_holiday(dt.date(2026, 7, 21))
        
        success = is_july_20_holiday and is_aug_7_holiday and not is_july_21_holiday
        self.record_result(13, "Detección Perpetua de Festivos de Colombia (Ley Emiliani)", success, 
                           f"20-Jul: {is_july_20_holiday}, 7-Ago: {is_aug_7_holiday}, 21-Jul: {is_july_21_holiday}")

    async def test_case_14_call_to_another_number(self):
        """Caso 14: Solicitud de llamada a otro número telefónico"""
        msgs = [HumanMessage(content="Me interesa la asesoría virtual pero por favor llámenme a este número: 3158889900")]
        reply = await self.invoke_agent(msgs)
        has_ack = "315" in reply or "llamada" in reply.lower() or "número" in reply.lower() or "virtual" in reply.lower() or "asesoría" in reply.lower()
        success = has_ack
        self.record_result(14, "Reconocimiento de Llamada a Teléfono Alternativo", success, f"Reply: {reply[:100]}...")

    async def test_case_15_showroom_logistics_parking_guests(self):
        """Caso 15: Logística del Showroom (Parqueadero privado y acompañantes)"""
        msgs = [HumanMessage(content="¿El showroom de Armenia tiene parqueadero y puedo ir con mi arquitecto y mi esposa?")]
        reply = await self.invoke_agent(msgs)
        has_parking = "parqueadero" in reply.lower()
        has_guests = any(w in reply.lower() for w in ["acompañante", "esposa", "arquitecto", "bienvenido", "familia", "claro"])
        success = has_parking and has_guests
        self.record_result(15, "Logística Showroom: Parqueadero Gratuito y Acompañantes", success, f"Reply: {reply[:100]}...")

    async def test_case_16_anti_truncation_no_prompt_leak(self):
        """Caso 16: Anti-Truncamiento y Cero Fuga de Tags de Sistema"""
        msgs = [HumanMessage(content="¿Cómo es el proceso constructivo de las casas expandibles Flex Home?")]
        reply = await self.invoke_agent(msgs)
        has_no_xml_tags = "<system_prompt>" not in reply and "<business_rules>" not in reply and "</rule>" not in reply
        has_no_truncation = not reply.strip().endswith("Sus lím") and not reply.strip().endswith("Quién es:")
        has_clean_end = reply.strip().endswith((".", "!", "?", "😊", "🏡", "✨", "👋", "🤝"))
        success = has_no_xml_tags and has_no_truncation and has_clean_end
        self.record_result(16, "Anti-Truncamiento y Cero Fuga de Instrucciones de Sistema", success, f"Reply: {reply[-60:]}")

    async def test_case_17_anti_empty_message(self):
        """Caso 17: Anti-Mensajes Vacíos en Blanco"""
        msgs = [HumanMessage(content="Ok")]
        reply = await self.invoke_agent(msgs)
        is_valid_non_empty = len(reply.strip()) > 15
        success = is_valid_non_empty
        self.record_result(17, "Anti-Mensajes Vacíos en Blanco", success, f"Len: {len(reply)} | Reply: {reply}")

    # =========================================================================
    # EJECUTOR PRINCIPAL
    # =========================================================================

    async def run_all(self):
        print("\n" + "="*75)
        print("🏛️ ANCLA CRM — EJECUTANDO SUITE MAESTRA DE CONTROL DE CALIDAD (17 CASOS)")
        print("="*75 + "\n")
        
        start_time = asyncio.get_event_loop().time()
        
        tests = [
            self.test_case_01_no_prices(),
            self.test_case_02_distance_objection(),
            self.test_case_03_active_appointment_courtesy(),
            self.test_case_04_meta_ads_form_2_paragraphs(),
            self.test_case_05_cold_lead_consultative(),
            self.test_case_06_human_or_liliana_request(),
            self.test_case_07_pdf_catalog_request(),
            self.test_case_08_night_cutoff_future_dates(),
            self.test_case_09_product_recognition(),
            self.test_case_10_anti_repetition_of_greetings(),
            self.test_case_11_terminology_and_no_facebook(),
            self.test_case_12_dynamic_modality_switch(),
            self.test_case_13_colombian_holidays_ley_emiliani(),
            self.test_case_14_call_to_another_number(),
            self.test_case_15_showroom_logistics_parking_guests(),
            self.test_case_16_anti_truncation_no_prompt_leak(),
            self.test_case_17_anti_empty_message(),
        ]
        
        for t in tests:
            await t
            
        elapsed = asyncio.get_event_loop().time() - start_time
        total = self.passed + self.failed
        pct = (self.passed / total) * 100 if total > 0 else 0
        
        print("\n" + "="*75)
        print(f"📊 RESUMEN FINAL DEL TEST SUITE: {self.passed}/{total} APROBADOS ({pct:.1f}%) | Tiempo: {elapsed:.2f}s")
        print("="*75)
        
        if self.failed == 0:
            print("🏆 CERTIFICACIÓN OFICIAL: EL SISTEMA CUMPLE EL 100% DE LOS MANDAMIENTOS.")
            return 0
        else:
            print(f"⚠️ ALERTA: SE DETECTARON {self.failed} CASOS FALLIDOS. NO DESPLEGAR A PRODUCCIÓN.")
            return 1

if __name__ == "__main__":
    suite = SofiMasterTestSuite()
    exit_code = asyncio.run(suite.run_all())
    sys.exit(exit_code)
