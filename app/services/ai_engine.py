import os
import logging
import httpx
import datetime as dt_module
from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.config import settings
from app.models.base import Contact, Availability, Appointment, PipelineStage, SystemSetting, Message, SenderType

logger = logging.getLogger("ai_engine")

class AIEngine:
    def __init__(self):
        # API Key por defecto de las variables de entorno
        self.api_key = settings.GEMINI_API_KEY
        self.model = "gemini-3.5-flash"
        self.api_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent"

    def _get_api_key(self, db: Session) -> Optional[str]:
        """
        Retorna la clave API de Gemini configurada. Prioriza la base de datos sobre el archivo .env.
        """
        db_key = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
        if db_key and db_key.value:
            return db_key.value
        return self.api_key

    def get_dynamic_days_list(self) -> str:
        import datetime as dt
        now = dt.datetime.now()
        days_es = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        months_es = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        
        lines = []
        num = 1
        for i in range(1, 8):
            target_date = now + dt.timedelta(days=i)
            if target_date.weekday() == 6: # Skip Sunday
                continue
            if num > 6:
                break
            day_name = days_es[target_date.weekday()]
            month_name = months_es[target_date.month]
            rel_label = " (Mañana)" if i == 1 else ""
            lines.append(f"• **{num}️⃣ {day_name} {target_date.day} de {month_name}{rel_label}**")
            num += 1
            
        return "\n".join(lines)

    def get_dynamic_showroom_options(self, is_virtual: bool = False) -> str:
        if is_virtual:
            return (
                "¡Hola! 🏠✨ Gracias por registrarte en ANCLA Special Projects.\n\n"
                "Hemos recibido tu solicitud para coordinar tu **Asesoría Virtual (Google Meet / Zoom o Llamada Telefónica)**.\n\n"
                "Disponemos de horarios diurnos de **Lunes a Viernes (10:00 AM - 12:00 PM y 2:00 PM - 4:30 PM)** y **Sábados (10:00 AM - 12:00 PM)**.\n\n"
                "¿Qué día y jornada te queda más cómodo para agendar tu espacio exclusivo?"
            )
            
        return (
            "¡Hola! 🏠✨ Gracias por escribir a **ANCLA Special Projects**.\n\n"
            "Te invitamos a conocer nuestras casas modulares exhibidas (Flex Home y Cápsula Living). Ofrecemos dos modalidades de atención personalizada:\n\n"
            "1️⃣ **Visita Presencial en Showroom Armenia** (Av. Centenario, frente a Pan y Miel — Lunes a Viernes: 9:30 AM a 12:00 PM y 2:00 PM a 4:00 PM, máx 2 citas por hora).\n"
            "2️⃣ **Asesoría Virtual / Llamada Comercial** (Ideal si estás en otra ciudad o prefieres llamada de asesoría).\n\n"
            "📍 **GPS Google Maps**: https://maps.google.com/?q=4.5616751,-75.6455612\n\n"
            "¿Qué modalidad prefieres para coordinar tu atención?"
        )

    async def generate_copilot_suggestion(self, conversation_history: List[Dict[str, Any]], db: Session = None) -> str:
        """
        Genera una sugerencia de respuesta (Copiloto) basada en los últimos mensajes usando Google Gemini.
        """
        api_key = self.api_key
        if db:
            api_key = self._get_api_key(db)

        if not api_key:
            return self._heuristic_copilot(conversation_history)

        url = f"{self.api_url}?key={api_key}"
        
        system_instruction = (
            "Actúas como un copiloto de IA en un CRM. Sugiere una respuesta concisa, "
            "persuasiva y amigable al último mensaje del cliente. Mantén la respuesta en español."
        )
        
        # Estructurar el historial para Gemini
        chat_context = []
        for msg in conversation_history[-10:]:
            role = "model" if msg["sender_type"] in ["user", "ai"] else "user"
            chat_context.append(f"{role}: {msg['content']}")

        prompt = "Historial del chat:\n" + "\n".join(chat_context) + "\n\nSugiere la mejor respuesta:"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {"text": system_instruction}
                ]
            },
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 200
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=12.0)
                if response.status_code == 200:
                    data = response.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    logger.error(f"Error en Gemini API (Copilot): {response.text}")
                    return self._heuristic_copilot(conversation_history)
        except Exception as e:
            logger.error(f"Error llamando a Gemini para Copiloto: {e}")
            return self._heuristic_copilot(conversation_history)

    async def _classify_intent_by_llm(self, last_message: str, api_key: str) -> str:
        """
        Llama a Gemini a temperatura 0.0 para clasificar la intención en: CITAS, VENTAS, INFORMATIVO o HUMANO.
        """
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        is_openrouter = api_key.startswith("sk-or-v1")
        if is_openrouter:
            url = "https://openrouter.ai/api/v1/chat/completions"
            
        system_instruction = (
            "Clasifica el mensaje del cliente en una de las siguientes intenciones:\n"
            "- CITAS: Si el cliente quiere agendar, programar, una reunión, que lo llamen, cita por Meet, o coordinar disponibilidad.\n"
            "- INFORMATIVO: Si el cliente busca la dirección física, cómo llegar al showroom, entrada a la inauguración, horarios de atención, o la lista de modelos de catálogo de casas.\n"
            "- VENTAS: Si el cliente tiene dudas de materiales, precios, aislamiento térmico, cómo comprar, especificaciones, metros cuadrados, o solicita información técnica.\n"
            "- HUMANO: Si pide expresamente hablar con una persona, asesor, humano, o que el bot se desactive.\n\n"
            "Devuelve ÚNICAMENTE la palabra correspondiente (CITAS, VENTAS, INFORMATIVO, HUMANO)."
        )
        
        payload = {}
        if is_openrouter:
            payload = {
                "model": os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat"),
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": last_message}
                ],
                "temperature": 0.0
            }
        else:
            payload = {
                "contents": [{"parts": [{"text": last_message}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {"temperature": 0.0}
            }
            
        try:
            async with httpx.AsyncClient() as client:
                headers = {}
                if is_openrouter:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://anclaspecialprojects.com",
                        "X-Title": "ANCLA Special Projects CRM"
                    }
                res = await client.post(url, json=payload, headers=headers, timeout=6.0)
                if res.status_code == 200:
                    data = res.json()
                    if is_openrouter:
                        reply = data["choices"][0]["message"]["content"].strip().upper()
                    else:
                        reply = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
                    if reply in ["CITAS", "VENTAS", "INFORMATIVO", "HUMANO"]:
                        return reply
        except Exception as e:
            logger.error(f"Error en clasificador LLM de intención: {e}")
            
        return "UNKNOWN"

    async def _call_llm(self, api_key: str, system_instruction: str, prompt: str, temperature: float = 0.6) -> str:
        """
        Helper genérico para llamar a Gemini o OpenRouter con temperatura y system instruction customizadas.
        """
        is_openrouter = api_key.startswith("sk-or-v1")
        if is_openrouter:
            openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://anclaspecialprojects.com",
                "X-Title": "ANCLA Special Projects CRM"
            }
            # Modelos de OpenRouter priorizados por inteligencia y adherencia a instrucciones
            openrouter_models = [
                os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-chat"),
                "anthropic/claude-3.5-sonnet",
                "openai/gpt-4o",
                "google/gemini-2.5-pro",
                "google/gemini-2.0-flash-001"
            ]
            for model_name in openrouter_models:
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": temperature,
                    "max_tokens": 800
                }
                try:
                    async with httpx.AsyncClient() as client:
                        res = await client.post(openrouter_url, headers=headers, json=payload, timeout=12.0)
                        if res.status_code == 200:
                            data = res.json()
                            return data["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    logger.warning(f"Fallo en OpenRouter {model_name} en llamada directa: {e}")
        else:
            for mod_name in ["gemini-2.5-flash", "gemini-1.5-flash"]:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{mod_name}:generateContent?key={api_key}"
                payload = {
                    "contents": [{"parts": [{"text": prompt}]}],
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": 350
                    }
                }
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(url, json=payload, timeout=12.0)
                        if response.status_code == 200:
                            data = response.json()
                            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                except Exception as e:
                    logger.warning(f"Fallo en Google direct {mod_name}: {e}")
                    
        return ""

    async def generate_autopilot_reply(self, db: Session, contact: Contact, last_message: str) -> Optional[str]:
        """
        Genera una respuesta autónoma conversacional multi-agente utilizando la orquestación de LangGraph.
        """
        low_msg = (last_message or "").lower().strip()

        # --- 0.0 EVITAR RESPUESTAS DUPLICADAS DURANTE AGENDAMIENTO INTERACTIVO ---
        if contact.scheduling_state:
            logger.info(f"Sofi: Contacto {contact.phone} en estado interactivo ({contact.scheduling_state}). Evitando respuesta duplicada del autopiloto.")
            return None

        # --- 0.A SILENCIO ABSOLUTO EN MODO CO-PILOTO HUMANO ---
        if not contact.chatbot_enabled:
            scheduling_keywords = ["agendar", "cita", "reprogramar", "llamar", "llamada", "showroom", "visitar", "visita", "quiero ir"]
            is_requesting_appointment = any(k in low_msg for k in scheduling_keywords)
            if not is_requesting_appointment:
                logger.info(f"Sofi: Chatbot desactivado o en modo co-piloto humano para {contact.phone}. Manteniendo silencio absoluto.")
                return None
            else:
                logger.info(f"Sofi: Cliente en modo humano solicitó agendamiento expreso ({last_message}). Atendiendo solicitud.")

        # --- 0.B DETECCIÓN PRIORITARIA DE CIERRE / DESPEDIDA / CORTESÍA (1 LÍNEA) ---
        goodbye_phrases = ["hasta luego", "hasta pronto", "chao", "adiós", "adios", "nos vemos", "me voy a dormir", "a dormir", "no gracias", "no muchas gracias", "no, gracias", "listo gracias", "ok gracias", "gracias, hasta luego", "gracias por la información", "gracias por la informacion", "gracias, muy amable", "gracias muy amable", "agradezco", "agradecido", "agradecida", "vale gracias", "ok vale"]
        is_closing = any(p in low_msg for p in goodbye_phrases) or (any(w in low_msg for w in ["gracias", "agradezco", "agradecido", "agradecida"]) and len(low_msg) < 45)

        if is_closing:
            import datetime as dt_cls
            recent_closing = db.query(Message).filter(
                Message.contact_id == contact.id,
                Message.sender_type == SenderType.AI,
                Message.created_at >= dt_cls.datetime.utcnow() - dt_cls.timedelta(hours=12)
            ).first()

            if recent_closing:
                logger.info(f"Sofi: Cierre o agradecimiento detectado en '{last_message}' para {contact.phone}. Ya existe respuesta reciente en 12h. Cerrando en silencio definitivo.")
                return None

            c_name = f"{contact.first_name or ''}".strip() or "estimado/a cliente"
            if "noche" in low_msg or "dormir" in low_msg or "descans" in low_msg:
                reply = f"¡Descansa, {c_name}! Buenas noches y dulces sueños. 🌙✨ Quedamos a tu total disposición para cuando desees retomar tu proyecto. ¡Hasta pronto! 🏡🤝"
            else:
                reply = f"¡Con mucho gusto, {c_name}! Que tengas un excelente día. 🌟 Quedamos 100% atentos a tu proyecto para cuando desees continuar. ¡Hasta pronto! 🏡🤝"

            logger.info(f"Sofi: Cierre de conversación para {contact.phone}. Enviando despedida ultracorta de cierre: '{reply}'")
            return reply

        from langgraph.graph import StateGraph, END
        from typing import TypedDict

        class AgentState(TypedDict):
            db: Session
            contact: Contact
            last_message: str
            next_node: str
            response: Optional[str]

        # --- NODOS DEL GRAFO DE AGENTES ---

        async def orchestrator_node(state: AgentState) -> dict:
            """
            Orquestador Principal: Clasifica intenciones y enruta la conversación. (Temp 0.0)
            """
            db = state["db"]
            contact = state["contact"]
            msg = state["last_message"]
            msg_lower = msg.lower().strip()

            from app.services.activity import record_activity

            # EXTRACCIÓN AUTOMÁTICA DE ESTADO DE LOTE Y CIUDAD EN TIEMPO REAL (TIPO META ADS)
            lot_keywords_yes = ["sí tengo lote", "si tengo lote", "tengo lote", "lote propio", "tengo terreno", "tengo la finca", "tengo la parcela", "sí tengo terreno", "si tengo terreno", "ya tengo lote", "ya tengo terreno"]
            lot_keywords_no = ["no tengo lote", "no tengo terreno", "buscando lote", "no cuento con lote", "sin lote", "buscando terreno", "busco lote", "no tengo el lote"]

            if any(k in msg_lower for k in lot_keywords_yes):
                contact.lot_status = "Lote Propio"
                db.add(contact)
                db.commit()
            elif any(k in msg_lower for k in lot_keywords_no):
                contact.lot_status = "Buscando Lote"
                db.add(contact)
                db.commit()

            ciudades_comunes = ["armenia", "filandia", "salento", "quimbaya", "circasia", "calarcá", "calarca", "pereira", "manizales", "bogotá", "bogota", "medellín", "medellin", "cali", "ibagué", "ibague", "pasto", "popayán", "popayan", "neiva", "tunja", "paipa", "montenegro", "la tebaida"]
            for c_city in ciudades_comunes:
                if c_city in msg_lower:
                    contact.lot_city = c_city.capitalize()
                    db.add(contact)
                    db.commit()
                    break

            # AUTO-EXTRACCIÓN DE PERFIL Y RUTA DESDE EL FORMULARIO DE META ADS
            is_form_submission = bool(msg and ("full name:" in msg_lower or "completé el formulario" in msg_lower or "lead ads payload" in msg_lower))

            if msg and ("full name:" in msg_lower or "completé el formulario" in msg_lower):
                import re
                nm = re.search(r'Full name:\s*([^\n\r]+)', msg, re.IGNORECASE)
                em = re.search(r'Email:\s*([^\n\r]+)', msg, re.IGNORECASE)
                city_m = re.search(r'construir tu proyecto\?:?\s*([^\n\r]+)', msg, re.IGNORECASE)
                
                if nm:
                    fn_parts = nm.group(1).strip().split()
                    if fn_parts:
                        contact.first_name = fn_parts[0]
                        contact.last_name = ' '.join(fn_parts[1:]) if len(fn_parts) > 1 else ''
                if em:
                    raw_em = em.group(1).strip().lower()
                    if '@' in raw_em:
                        contact.email = raw_em
                if city_m:
                    contact.lot_city = city_m.group(1).strip()
                if 'sí, ya tengo' in msg_lower or 'si, ya tengo' in msg_lower or 'ya tengo' in msg_lower:
                    contact.lot_status = "Lote Propio"
                elif 'buscando' in msg_lower or 'no tengo' in msg_lower:
                    contact.lot_status = "Buscando Lote"

                db.add(contact)
                db.commit()

            # SI ES UN FORMULARIO AUTOMÁTICO DE META ADS REAL, RECONOCER SUS ELECCIONES
            if is_form_submission:
                c_fn = contact.first_name or "cliente"
                city_str = f" en **{contact.lot_city}**" if contact.lot_city else ""
                lot_str = f"registramos que cuentas con terreno propio{city_str}" if contact.lot_status == "Lote Propio" else "registramos tu solicitud"
                
                pref_mod = "Asesoría Personalizada"
                if "llamada" in msg_lower:
                    pref_mod = "Llamada Telefónica Comercial"
                elif "visita" in msg_lower or "showroom" in msg_lower:
                    pref_mod = "Visita Presencial en Showroom Armenia"
                elif "virtual" in msg_lower:
                    pref_mod = "Asesoría Virtual (Google Meet / Zoom)"

                return {
                    "response": (
                        f"¡Hola {c_fn}! 🏠✨ Gracias por registrarte en **ANCLA Special Projects**.\n\n"
                        f"Hemos recibido tu formulario completado: {lot_str} y seleccionaste **{pref_mod}**.\n\n"
                        f"Disponemos de horarios diurnos de Lunes a Sábado para tu atención exclusiva (10:00 AM - 12:00 PM y 02:00 PM - 04:30 PM).\n\n"
                        f"¿Qué día y horario te queda más cómodo para coordinar tu atención?"
                    )
                }

            # SI ES UN SALUDO SIMPLE U ORGÁNICO HUMANO (ej: "Hola buenas tardes, ¿cómo están?")
            pure_greetings = ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "hola!", "hola buenas tardes", "hola como estan", "hola como esta", "buenas tardes como estan", "buenas tardes como esta", "hola buenas tardes como estan", "como estan", "como esta"]

            if any(msg_lower.strip() == g for g in pure_greetings) or ("como est" in msg_lower and len(msg_lower) < 40) or (msg_lower.startswith("hola") and len(msg_lower) < 25 and not any(k in msg_lower for k in ["precio", "costo", "lote", "informacion", "catálogo", "catalogo"])):
                if contact.first_name and not contact.first_name.startswith("+") and contact.first_name.lower() not in ["cliente", "estimado cliente"]:
                    return {
                        "response": (
                            f"¡Hola {contact.first_name}! 👋 Buenas tardes, muy bien gracias a Dios. 😊\n\n"
                            f"Cuéntame, ¿en qué te podemos colaborar el día de hoy o qué proyecto tienes en mente?"
                        )
                    }
                else:
                    return {
                        "response": (
                            "¡Hola! 👋 Buenas tardes, muy bien gracias a Dios. 😊\n\n"
                            "Te habla Sofía de **ANCLA Special Projects**. ¿Con quién tengo el gusto de hablar y en qué te podemos ayudar el día de hoy?"
                        )
                    }

            # PASO 0: DETECCIÓN PRIORITARIA DE INTENCIONES ESPECÍFICAS DE PREGUNTA
            explicit_virtual_phrases = [
                "puedo virtual", "no puedo presencial", "no estoy en armenia", "estoy en otra ciudad", "estoy fuera", 
                "atención virtual", "asesoría virtual", "modo virtual", "asesoria virtual", "otra región", "otra region",
                "me queda difícil", "me queda dificil", "complicado ir", "difícil asistir", "dificil asistir",
                "trabajo en", "estoy en nariño", "en nariño", "estoy en bogota", "estoy en medellin", "estoy en cali",
                "viajo desde", "fuera de armenia", "lejos de armenia", "no puedo ir", "no puedo asistir"
            ]
            is_virtual_lead = (contact.qualification_notes and "[LISTA_ESPERA_VIP]" in contact.qualification_notes) or any(w in msg_lower for w in explicit_virtual_phrases)

            if is_virtual_lead and "[LISTA_ESPERA_VIP]" not in (contact.qualification_notes or ""):
                contact.qualification_notes = f"[LISTA_ESPERA_VIP]\n{contact.qualification_notes or ''}"
                db.add(contact)
                db.commit()

            current_now = datetime.now()
            today_date = current_now.date()
            
            # Mapeo estricto de días
            dias_semana = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
            meses_ano = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            
            nombre_dia_hoy = dias_semana[today_date.weekday()]
            nombre_mes_hoy = meses_ano[today_date.month - 1]
            fecha_hoy_legible = f"{nombre_dia_hoy} {today_date.day} de {nombre_mes_hoy}"

            # Si ya pasaron las 6:00 PM (18:00) del Miércoles 29 o ya estamos a 30 de Julio en adelante
            is_inauguration_over = (today_date > datetime.date(2026, 7, 29)) or (today_date == datetime.date(2026, 7, 29) and current_now.hour >= 18)

            if not is_inauguration_over:
                showroom_dates_str = "¡Hoy Miércoles 29 de Julio (Cierre de la Gran Inauguración VIP)!"
                showroom_callout = "¡Hoy es el último día de Gran Inauguración de nuestro Showroom!"
            else:
                showroom_dates_str = "Atención permanente post-inauguración: Lunes a Sábado (Jornada Mañana: 10:00 AM a 12:00 PM | Jornada Tarde: 02:00 PM a 04:00 PM — máximo 2 citas por hora)"
                showroom_callout = "Atención permanente post-inauguración en Showroom Armenia"

            gps_links_text = (
                "📍 **UBICACIÓN Y ENLACES GPS SHOWROOM ARMENIA**\n\n"
                "🏢 **Dirección**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n"
                f"🗓️ **Horario de Atención**: {showroom_dates_str}\n\n"
                "🚗 **Toca el enlace para iniciar la ruta GPS:**\n"
                "🔹 **Google Maps Ubicación Oficial**: https://maps.google.com/?q=4.5616751,-75.6455612"
            )

            # COMPROBAR SI YA EXISTE CITA CONFIRMADA FUTURA ANTES DE PROCESAR FORMULARIO O MENSAJES
            from app.models.base import Appointment
            from datetime import datetime as dt_now
            existing_app = db.query(Appointment).filter(
                Appointment.contact_id == contact.id,
                Appointment.status == "CONFIRMED",
                Appointment.datetime >= dt_now.utcnow()
            ).order_by(Appointment.created_at.desc()).first()

            # MANEJO DIRECTO DE NUEVO FORMULARIO META ADS O MENÚ ABIERTO
            if is_form_submission:
                if existing_app:
                    date_str = existing_app.datetime.strftime("%A %d de %B a las %I:%M %p")
                    day_translations = {
                        "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
                        "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
                        "January": "Enero", "February": "Febrero", "March": "Marzo", "April": "Abril",
                        "May": "Mayo", "June": "Junio", "July": "Julio", "August": "Agosto",
                        "September": "Septiembre", "October": "Octubre", "November": "Noviembre", "December": "Diciembre"
                    }
                    for en, es in day_translations.items():
                        date_str = date_str.replace(en, es)
                    
                    return {
                        "next_node": "end",
                        "response": (
                            f"¡Hola {contact.first_name or ''}! 👋 Te confirmamos que hemos recibido tu registro publicitario. "
                            f"Queremos darte total tranquilidad de que **tu cita ya se encuentra agendada y confirmada** en nuestro sistema:\n\n"
                            f"📅 **Fecha y Hora**: {date_str}\n"
                            f"📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n\n"
                            f"Acabamos de actualizar la Ficha Técnica de tu proyecto con los nuevos datos recibidos. ¡Te esperamos! 🏡🤝"
                        )
                    }

                # Enrutar todos los nuevos leads de Meta directamente al flujo interactivo de agendamiento
                logger.info(f"Sofi: Nuevo lead de Meta Ads ({contact.first_name}). Enrutando a citas.")
                record_activity(db, contact.id, "ai_routing", "Sofi: Nuevo lead de Meta Ads. Enrutando a citas.")
                return {"next_node": "citas"}

            # A. Detección explícita de solicitud de información para asistir / ubicación / fechas / waze / maps
            if not is_virtual_lead and any(w in msg_lower for w in ["quiero asistir", "quiero ir", "como asistir", "cómo asistir", "informacion para asistir", "información para asistir", "ubicacion", "ubicación", "donde estan", "dónde están", "inauguracion", "inauguración", "waze", "maps", "mapa", "como llegar", "cómo llegar", "donde queda", "dónde queda", "direccion", "dirección", "donde es", "dónde es"]):
                return {
                    "response": (
                        f"¡Hola {contact.first_name or ''}! 👋 Con mucho gusto te compartimos los datos de ubicación y GPS de nuestro Showroom en Armenia: 🏠✨\n\n"
                        f"{gps_links_text}\n\n"
                        f"¿Qué día prefieres visitarnos? ¿Y en qué jornada (mañana o tarde) te queda mejor para reservar tu cupo de atención personalizada?"
                    )
                }

            # B. Detección específica por producto solicitado (Cuartos Fríos)
            if any(w in msg_lower for w in ["cuarto frio", "cuartos frios", "cuarto frío", "cuartos fríos", "refrigeracion", "refrigeración", "congelacion", "congelación"]):
                return {"response": (
                    f"¡Con mucho gusto, {contact.first_name or ''}! ❄️🏗️ En **ANCLA Special Projects** diseñamos y construimos **Cuartos Fríos y Bodegas de Refrigeración Modulares** a la medida de tu negocio o industria:\n\n"
                    f"• **Paneles Aislantes de Alta Eficiencia**: Estructura inyectada en poliuretano (PUR/PIR) de alto grosor para conservación (+4°C) o congelación (-20°C).\n"
                    f"• **Equipos e Instalación Sanitaria**: Unidades condensadoras industriales, puertas herméticas y acabados de fácil limpieza para normas sanitarias.\n\n"
                    f"Como la potencia frigorífica, dimensiones y compresores se calculan a la medida de tu carga y ubicación, los planos y la cotización técnica te los presenta nuestro **asesor especialista en proyectos modulares e industriales** en tu Asesoría Virtual por llamada o Google Meet.\n\n"
                    f"¿Te gustaría que vayamos agendando tu espacio en la mañana o en la tarde?"
                )}

            # C. Escalación manual rápida
            explicit_human_phrases = ["hablar con humano", "quiero un humano", "asesor humano", "hablar con un asesor", "hablar con una persona", "persona real", "/humano"]
            if any(p in msg_lower for p in explicit_human_phrases):
                contact.chatbot_enabled = False
                db.add(contact)
                db.commit()
                record_activity(db, contact.id, "chatbot_toggle", "Sofi: Desactivada y conversación transferida a asesor humano por solicitud explícita.")
                return {
                    "next_node": "end",
                    "response": "👤 He transferido tu conversación a nuestro equipo de asesores humanos. Un especialista te atenderá de inmediato."
                }

            # E. Enrutamiento forzoso por estado de agendamiento activo en base de datos
            if contact.scheduling_state in ["AWAITING_PREFERENCE", "AWAITING_TIME", "AWAITING_CONFIRMATION"]:
                logger.info(f"Sofi: Estado de agendamiento activo '{contact.scheduling_state}'. Enrutando ineludiblemente a citas.")
                record_activity(db, contact.id, "ai_routing", f"Sofi: Agendamiento activo '{contact.scheduling_state}'. Enrutando a citas.")
                return {"next_node": "citas"}

            # B.1. Detección prioritaria e ineludible de Agendamiento / Llamadas / Citas (Garantiza flujo interactivo)
            booking_words = ["agendar", "cita", "reunion", "reunión", "meet", "llamen", "llame", "llamada", "llamar", "telefono", "teléfono", "/agendar", "5pm", "5 pm", "5:00", "a las 5", "reprogramar", "mar28", "mie29", "martes", "miércoles", "miercoles", "miérc", "mierc", "28 de julio", "29 de julio", "28 julio", "29 julio", "virtual", "presencial", "confirmar", "confirmo"]
            distant_cities = ["buga", "medellin", "medellín", "bogota", "bogotá", "cali", "cartagena", "barranquilla", "bucaramanga", "popayan", "pasto", "cucuta", "ibague", "neiva", "tunja", "manizales", "pereira", "valle", "antioquia", "cundinamarca"]
            
            if any(w in msg_lower for w in booking_words) or any(c in msg_lower for c in distant_cities):
                logger.info(f"Detección directa prioritaria de CITAS/CIUDAD por palabra clave en mensaje: '{msg}'")
                record_activity(db, contact.id, "ai_routing", "Sofi: Detección prioritaria de CITAS/CIUDAD. Enrutando a citas.")
                return {"next_node": "citas"}

            # C. Consultar clasificador por LLM para casos ambiguos
            api_key = self._get_api_key(db) or settings.GEMINI_API_KEY
            intent = await self._classify_intent_by_llm(msg, api_key)
            logger.info(f"Intención clasificada por LLM: {intent}")
            record_activity(db, contact.id, "ai_routing", f"Sofi: Intención clasificada por LLM: {intent}")

            if intent == "CITAS":
                return {"next_node": "citas"}
            elif intent == "INFORMATIVO":
                return {"next_node": "informativo"}
            elif intent == "VENTAS":
                return {"next_node": "ventas"}

            # D. Clasificador de contingencia (regex tradicional)
            if any(w in msg_lower for w in ["agendar", "cita", "reunion", "reunión", "meet", "llamen", "llame", "llamada", "llamar", "telefono", "teléfono", "/agendar"]):
                record_activity(db, contact.id, "ai_routing", "Sofi: Contingencia regex - Enrutando a citas")
                return {"next_node": "citas"}
            elif any(w in msg_lower for w in ["inauguracion", "inauguración", "evento", "showroom", "ubicacion", "ubicación", "direccion", "dirección", "modelos", "catalogo", "catálogo", "casas"]):
                record_activity(db, contact.id, "ai_routing", "Sofi: Contingencia regex - Enrutando a informativo")
                return {"next_node": "informativo"}
            
            # Default
            record_activity(db, contact.id, "ai_routing", "Sofi: Intención por defecto. Enrutando a ventas.")
            return {"next_node": "ventas"}

        async def appointments_agent_node(state: AgentState) -> dict:
            """
            Agente de Citas/Agendamiento: Extrae fechas y gestiona slots en Google Calendar y DB. (Temp 0.0)
            """
            db = state["db"]
            contact = state["contact"]
            msg = state["last_message"]
            msg_lower = msg.lower().strip()

            # FILTRO INTELIGENTE DE AUDIOS ACCIDENTALES / RUIDO DE FONDO NO RELEVANTE
            if any(w in msg_lower for w in ["[audio]", "[nota de voz]", "audio recibido", "nota de voz recibida"]):
                booking_keywords = ["cita", "hora", "mañana", "viernes", "lunes", "martes", "miércoles", "jueves", "sábado", "presencial", "virtual", "lote", "precio", "sí", "confirmar", "agendar", "showroom", "10", "11", "12", "2", "3", "4"]
                if not any(kw in msg_lower for kw in booking_keywords):
                    logger.info(f"Sofi: Audio/nota de voz accidental ignorada en silencio para {contact.id}")
                    record_activity(db, contact.id, "audio_filter", f"Sofi: Audio accidental o no relevante omitido en silencio: '{msg}'")
                    return {
                        "response": None,
                        "silent": True
                    }

            # EXTRAER CORREO ELECTRÓNICO Y NOMBRE AUTOMÁTICAMENTE
            import re
            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', msg)
            if email_match:
                contact.email = email_match.group(0).lower().strip()
                db.add(contact)
                db.commit()
                logger.info(f"Sofi: Correo electrónico guardado para {contact.id}: {contact.email}")

            # Verificar si ya se ha saludado previamente
            from app.models.base import Message as DBMessage, SenderType
            already_greeted = db.query(DBMessage).filter(
                DBMessage.contact_id == contact.id,
                DBMessage.sender_type == SenderType.AI
            ).count() > 0
                
            # REGLA DE PROTECCIÓN DE NOMBRES DE CONTACTO:
            # Si el contacto ya tiene un nombre válido de más de 2 caracteres y no es genérico, NUNCA se sobrescribe.
            is_generic_name = not contact.first_name or len(contact.first_name.strip()) < 3 or contact.first_name.strip().lower() in ["si", "sí", ".", "hola", "user", "whatsapp"]

            if is_generic_name:
                name_match = re.search(r'(?:mi nombre es|me llamo|mi nombre:?|soy)\s+([a-zA-ZáéíóúÁÉÍÓÚñÑ\s]{2,30})', msg, re.IGNORECASE)
                if name_match:
                    extracted_name = name_match.group(1).strip()
                    name_words = extracted_name.split()
                    forbidden_starts = ["hola", "vivo", "quiero", "necesito", "por", "favor", "buenas", "dias", "tardes", "de", "en", "para", "llamada"]
                    if name_words and name_words[0].lower() not in forbidden_starts:
                        contact.first_name = name_words[0]
                        if len(name_words) > 1:
                            contact.last_name = " ".join(name_words[1:])
                        db.add(contact)
                        db.commit()
                        logger.info(f"Sofi: Nombre extraído y guardado para {contact.id}: {contact.first_name} {contact.last_name or ''}")

            # Comprobar si el mensaje ya contiene preferencias de horario (mañana, tarde, días)
            is_form_submission = any(w in msg_lower for w in ["completé el formulario", "form_id", "full name:", "podrás asistir presencialmente"])
            has_preferences = not is_form_submission and any(w in msg_lower for w in ["mañana", "tarde", "lunes", "martes", "miercoles", "miércoles", "jueves", "viernes", "28", "29", "10", "11", "12", "1", "2", "3", "4", "5"])

            # SUPERVISOR GUARDRAIL: Si el cliente ya tiene una cita confirmada FUTURA en BD (y no está enviando un nuevo formulario)
            from datetime import datetime as dt_now
            existing_app = db.query(Appointment).filter(
                Appointment.contact_id == contact.id,
                Appointment.status == "CONFIRMED",
                Appointment.datetime >= dt_now.utcnow()
            ).order_by(Appointment.created_at.desc()).first()

            # PRIORIDAD ABSOLUTA #1: SI EL CLIENTE HACE CLIC EN UN BOTÓN DE CONFIRMACIÓN O ENVÍA FRASE DE CONFIRMACIÓN
            confirm_phrases = ["sí, confirmar", "btn_confirm_slot", "confirmar", "sí, confirmar sábado", "sabado 10 am", "sábado 10 am", "sábado 10", "sabado 10", "10 am"]
            if any(cp in msg_lower for cp in confirm_phrases):
                # Si el cliente está respondiendo a una propuesta presencial o virtual para el Sábado o fecha específica
                target_dt = datetime(2026, 8, 1, 10, 0, 0) if any(w in msg_lower for w in ["sábado", "sabado", "10"]) else (existing_app.datetime if existing_app else datetime(2026, 8, 1, 10, 0, 0))
                
                app_obj = db.query(Appointment).filter(Appointment.contact_id == contact.id).order_by(Appointment.created_at.desc()).first()
                if not app_obj:
                    app_obj = Appointment(
                        contact_id=contact.id,
                        user_id=contact.assigned_user_id or 1,
                        datetime=target_dt,
                        status="CONFIRMED",
                        notes="Cita Confirmada por Botón / Chat"
                    )
                    db.add(app_obj)
                else:
                    app_obj.datetime = target_dt
                    app_obj.status = "CONFIRMED"
                    db.add(app_obj)
                
                contact.scheduling_state = "CONFIRMED"
                db.add(contact)
                db.commit()

                c_fn = contact.first_name or "estimado/a cliente"
                date_str = target_dt.strftime("%A %d de %B").title()
                time_str = target_dt.strftime("%I:%M %p")
                for en, es in [("Monday","Lunes"),("Tuesday","Martes"),("Wednesday","Miércoles"),("Thursday","Jueves"),("Friday","Viernes"),("Saturday","Sábado"),("Sunday","Domingo"),("August","Agosto"),("July","Julio")]:
                    date_str = date_str.replace(en, es)

                return {
                    "response": (
                        f"¡Excelente, {c_fn}! 👏✨ Tu cita ha quedado **100% REGISTRADA Y CONFIRMADA**.\n\n"
                        f"🗓️ **Fecha**: {date_str}\n"
                        f"⏰ **Hora**: {time_str}\n"
                        f"📍 **Ubicación Showroom**: Armenia, Quindío — Av. Centenario, frente a Pan y Miel.\n"
                        f"🗺️ **GPS Google Maps**: https://maps.google.com/?q=4.5616751,-75.6455612\n\n"
                        f"¡Nuestro equipo estará esperándote para brindarte la mejor atención! 🏡🤝"
                    )
                }

            if existing_app and not is_form_submission:
                c_name = contact.first_name or "estimado/a cliente"
                date_str = existing_app.datetime.strftime("%A %d de %B").title()
                time_str = existing_app.datetime.strftime("%I:%M %p")
                for en, es in [("Monday","Lunes"),("Tuesday","Martes"),("Wednesday","Miércoles"),("Thursday","Jueves"),("Friday","Viernes"),("January","Enero"),("February","Febrero"),("March","Marzo"),("April","Abril"),("May","Mayo"),("June","Junio"),("July","Julio"),("August","Agosto")]:
                    date_str = date_str.replace(en, es)
                
                # Si el cliente desea hablar con Liliana León o presiona el botón directo
                if any(w in msg_lower for w in ["btn_contact_liliana", "hablar con liliana", "contacto liliana", "directora", "hablar con la jefa"]):
                    if "[Atención Humana / Liliana León]" not in (contact.qualification_notes or ""):
                        contact.qualification_notes = f"[Atención Humana / Liliana León]\n{contact.qualification_notes or ''}"
                        db.add(contact)
                        db.commit()
                    return {
                        "response": f"¡Con mucho gusto, {c_name}! 📲 Puedes comunicarte o chatear directamente con **Liliana León** (Directora Líder de Ancla Special Projects) al celular **+57 320 287 6282**.\n\n👉 **Haz clic aquí para chatear con ella por WhatsApp**: https://wa.me/573202876282\n\n¡Ella y nuestro equipo estarán encantados de atenderte personalmente! 🏠✨"
                    }

                # Si el cliente está enviando una frase de cortesía, despedida o confirmación explícita
                courtesy_phrases = ["nos vemos", "hasta el", "gracias", "listo", "de acuerdo", "perfecto", "allá estaré", "alla nos vemos", "nos vemos el martes", "chao", "ok", "sí, confirmar", "btn_confirm_slot", "btn_yes", "btn_confirm_today"]
                if any(cp in msg_lower for cp in courtesy_phrases):
                    return {
                        "response": f"¡Excelente, {c_name}! Quedamos 100% agendados y confirmados. 👍✨ ¡Te esperamos el {date_str} a las {time_str} en nuestro Showroom de Armenia! Que tengas un excelente día. 🏡🤝"
                    }
                elif any(w in msg_lower.split() for w in ["hola", "buenos", "buenas", "que tal", "saludos"]):
                    return {
                        "response": f"¡Hola de nuevo, {c_name}! 👋 Te recuerdo que tu cita está confirmada para el {date_str} a las {time_str}. ¿Hay alguna duda adicional en la que te pueda ayudar hoy?"
                    }

            # AUTO-EXTRACCIÓN DE PERFIL Y RUTA DESDE EL FORMULARIO DE META ADS
            if last_message and ("full name:" in last_message.lower() or "completé el formulario" in last_message.lower()):
                import re
                nm = re.search(r'Full name:\s*([^\n\r]+)', last_message, re.IGNORECASE)
                em = re.search(r'Email:\s*([^\n\r]+)', last_message, re.IGNORECASE)
                if nm:
                    fn_parts = nm.group(1).strip().split()
                    if fn_parts:
                        contact.first_name = fn_parts[0]
                        contact.last_name = ' '.join(fn_parts[1:]) if len(fn_parts) > 1 else ''
                if em:
                    raw_em = em.group(1).strip().lower()
                    if '@' in raw_em:
                        contact.email = raw_em
                if 'no, estoy en otra región' in last_message.lower() or 'otra región' in last_message.lower():
                    notes = contact.qualification_notes or ''
                    if '[LISTA_ESPERA_VIP]' not in notes:
                        contact.qualification_notes = f"[LISTA_ESPERA_VIP]\n{notes}"
                db.add(contact)
                db.commit()

            # PASO 0: Detección prioritaria de opciones virtuales, botones o más información
            explicit_virtual_phrases = ["puedo virtual", "no puedo presencial", "no estoy en armenia", "estoy en otra ciudad", "estoy fuera", "atención virtual", "asesoría virtual", "modo virtual", "asesoria virtual", "otra región", "otra region", "boyaca", "paipa", "bogota", "medellin", "cali", "boyacá"]
            is_virtual_lead = (contact.qualification_notes and "[LISTA_ESPERA_VIP]" in contact.qualification_notes) or any(w in msg_lower for w in explicit_virtual_phrases)

            # DETECCIÓN EXPLÍCITA DE SELECCIÓN DE MODALIDAD DESDE BOTONES INTERACTIVOS
            if any(w in msg_lower for w in ["btn_mode_presencial", "btn_mode_presencial_org", "btn_mode_presencial_arm", "btn_mode_presencial_per", "visita presencial"]):
                contact.scheduling_state = "AWAITING_DAY"
                db.add(contact)
                db.commit()
                days_list_str = get_dynamic_days_list()
                return {
                    "response": (
                        f"¡Excelente elección, {c_name}! 🏠✨ Con gusto coordinamos tu **Visita Presencial en nuestro Showroom de Armenia** (Av. Centenario, frente a Pan y Miel).\n\n"
                        f"📍 **GPS Google Maps**: https://maps.google.com/?q=4.5616751,-75.6455612\n\n"
                        f"Selecciona a continuación el día de tu preferencia para reservar tu espacio exclusivo (atención de Lunes a Sábado):\n\n"
                        f"{days_list_str}\n\n"
                        f"¿Qué día prefieres para coordinar tu visita?"
                    )
                }

            if any(w in msg_lower for w in ["btn_mode_virtual", "btn_mode_virtual_org", "btn_mode_virtual_arm", "btn_mode_virtual_per", "asesoría virtual", "asesoria virtual", "llamada virtual", "modalidad virtual"]):
                contact.scheduling_state = "AWAITING_DAY"
                db.add(contact)
                db.commit()
                days_list_str = get_dynamic_days_list()
                return {
                    "response": (
                        f"¡Con mucho gusto, {c_name}! 💻✨ Registramos tu solicitud para **Asesoría Virtual (Google Meet / Zoom o Llamada Telefónica)**.\n\n"
                        f"Selecciona el día de tu preferencia para coordinar tu sesión personalizada (15 min):\n\n"
                        f"{days_list_str}\n\n"
                        f"¿Qué día prefieres para coordinar tu atención?"
                    )
                }

                # Verificar qué datos de calificación faltan en la Ficha del CRM
                missing_items = []
                if not contact.first_name or contact.first_name.startswith("+"):
                    missing_items.append("• **Tu Nombre Completo**")
                if not contact.email:
                    missing_items.append("• **Correo Electrónico**")
                
                notes_lower = (contact.qualification_notes or "").lower()
                has_city = any(loc in notes_lower for loc in ["paipa", "boyacá", "boyaca", "bogotá", "bogota", "medellín", "medellin", "cali", "manizales", "pereira", "bucaramanga", "cúcuta", "cucuta", "ibagué", "ibague", "pasto", "popayán", "popayan", "neiva", "tunja", "armenia", "ciudad", "municipio"])
                if not has_city:
                    missing_items.append("• **Ciudad / Municipio donde proyectas construir**")

                if missing_items:
                    fields_str = "\n".join(missing_items)
                    data_prompt = (
                        f"Para completar tu **Ficha de Atención VIP 100% registrada en nuestro sistema**, compártenos por favor:\n\n"
                        f"{fields_str}\n\n"
                        f"*(Ejemplo: Juan Ocampo - juan@gmail.com - Manizales)*\n\n"
                        f"Y coméntanos: **¿Cuentas actualmente con un terreno o lote propio?**"
                    )
                else:
                    data_prompt = (
                        f"¡Tus datos principales ({contact.first_name or ''} - {contact.email or ''}) ya se encuentran registrados en tu Ficha VIP! 📝\n\n"
                        f"Por último, coméntanos: **¿Cuentas actualmente con un terreno o lote propio?**"
                    )

                return {
                    "response": (
                        f"¡Hola {contact.first_name or ''}! 👋 Te informamos que debido a la Gran Inauguración de nuestro Showroom en Armenia, las asesorías virtuales y llamadas de esta semana se encuentran a **capacidad máxima (cupos 100% agotados)**. 🏡✨\n\n"
                        f"🌟 ¡No te preocupes! Has quedado registrado con prioridad en nuestra **Lista de Espera VIP**.\n\n"
                        f"El día **Jueves 30 de Julio** nuestro **asesor especialista en proyectos modulares** se comunicará directamente contigo por este medio para agendar la fecha y hora exacta de tu asesoría virtual para la próxima semana.\n\n"
                        f"{data_prompt}"
                    )
                }

            # Detección específica por producto solicitado
            if any(w in msg_lower for w in ["cuarto frio", "cuartos frios", "cuarto frío", "cuartos fríos", "refrigeracion", "refrigeración", "congelacion", "congelación"]):
                return {"response": (
                    f"¡Con mucho gusto, {contact.first_name or ''}! ❄️🏗️ En **ANCLA Special Projects** diseñamos y construimos **Cuartos Fríos y Bodegas de Refrigeración Modulares** a la medida de tu negocio o industria:\n\n"
                    f"• **Paneles Aislantes de Alta Eficiencia**: Estructura inyectada en poliuretano (PUR/PIR) de alto grosor para conservación (+4°C) o congelación (-20°C).\n"
                    f"• **Equipos e Instalación Sanitaria**: Unidades condensadoras industriales, puertas herméticas y acabados de fácil limpieza para normas sanitarias.\n\n"
                    f"Como la potencia frigorífica, dimensiones y compresores se calculan a la medida de tu carga y ubicación, los planos y la cotización técnica te los presenta nuestro **asesor especialista en proyectos modulares e industriales** en tu Asesoría Virtual por llamada o Google Meet a partir del Jueves 30 de Julio.\n\n"
                    f"¿Te gustaría que vayamos agendando tu espacio en la mañana o en la tarde?"
                )}

            if any(w in msg_lower for w in ["btn_virt_info", "btn_virt_cat", "ver catálogo", "catalogo antes", "ver catalogo", "más información", "mas informacion", "quiero información", "quiero informacion", "información", "informacion", "información de los modelos", "informacion de los modelos"]):
                opts_text = self.get_dynamic_showroom_options(is_virtual_lead)
                return {"response": (
                    f"¡Con mucho gusto, {contact.first_name or ''}! 🏠✨ Te compartimos la información de nuestros modelos principales:\n\n"
                    f"• **FLEX HOME (56m²)**: Casa modular expandible con 2 habitaciones, sala-comedor, cocineta y baño completo.\n"
                    f"• **CÁPSULA LINVIG (13m²)**: Suite premium con 1 habitación y 1 baño completo, ideal para espacios independientes o proyectos turísticos.\n\n"
                    f"Ambas estructuras cuentan con aislamiento termoacústico de alto confort.\n\n"
                    f"{opts_text}"
                )}

            # Detección explícita de solicitud de información para asistir / ubicación / fechas
            if not is_virtual_lead and any(w in msg_lower for w in ["quiero asistir", "quiero ir", "como asistir", "cómo asistir", "informacion para asistir", "información para asistir", "ubicacion", "ubicación", "donde estan", "dónde están", "inauguracion", "inauguración", "donde queda", "dónde queda", "como llegar", "cómo llegar", "direccion", "dirección", "donde es", "dónde es"]):
                return {
                    "response": (
                        f"¡Hola {contact.first_name or ''}! 👋 Con mucho gusto te brindamos la información para la Gran Inauguración de nuestro Showroom en Armenia. 🏠✨\n\n"
                        f"Te invitamos cordialmente a conocer nuestras casas modulares exhibidas (Flex Home y Cápsula Linvig).\n\n"
                        f"📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n"
                        f"🗓️ **Fechas de exhibición**: Martes 28 y Miércoles 29 de Julio (10:00 AM a 6:00 PM).\n\n"
                        f"¿Qué día prefieres visitarnos, el **Martes 28** o el **Miércoles 29 de Julio**? ¿Y en qué jornada (mañana o tarde) te queda mejor para reservar tu cupo de atención personalizada?"
                    )
                }

            # Detección explícita de origen Meta Ads o registro de formulario (Inauguración Showroom Armenia)
            is_meta_lead = is_form_submission or (contact.source and "meta" in contact.source.lower()) or (contact.qualification_notes and ("showroom_presencial" in contact.qualification_notes.lower() or "lead ads" in contact.qualification_notes.lower()))

            # Si el cliente es de la Lista de Espera VIP (Ruta B / Otra región), NO enviar invitación presencial
            if is_virtual_lead:
                return {
                    "response": (
                        f"¡Hola {contact.first_name or ''}! 👋 Gracias por registrarte en ANCLA Special Projects. 🏡✨\n\n"
                        f"Hemos notado que te encuentras fuera de la región o no podrás asistir presencialmente a nuestro Showroom en Armenia.\n\n"
                        f"🌟 ¡No te preocupes! Has quedado registrado en nuestra **Lista de Espera VIP** para atención personalizada virtual a partir del **Jueves 30 de Julio**.\n\n"
                        f"¿Te gustaría que vayamos agendando tu **Asesoría Virtual (Llamada 📞 / Google Meet 💻)** con nuestro **asesor especialista en proyectos modulares**?"
                    )
                }

            # Si NO se ha saludado previamente o es un nuevo registro de formulario, enviar la invitación presencial
            if is_form_submission or (not already_greeted and not has_preferences and not email_match):
                if is_meta_lead:
                    return {
                        "response": (
                            f"¡Hola {contact.first_name or ''}! 👋 Gracias por registrarte a la Gran Inauguración de nuestro Showroom en Armenia. 🏠✨\n\n"
                            f"Te invitamos cordialmente a conocer nuestras casas modulares exhibidas (Flex Home y Cápsula Linvig).\n\n"
                            f"📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n"
                            f"🗓️ **Fechas de exhibición**: Martes 28 y Miércoles 29 de Julio (10:00 AM a 6:00 PM).\n\n"
                            f"Selecciona el día de tu preferencia para tu visita presencial:"
                        )
                    }
                else:
                    return {
                        "response": (
                            "¡Hola! Gracias por escribir a ANCLA Special Projects. 🏠✨\n\n"
                            "Te invitamos cordialmente a conocer nuestras casas modulares exhibidas (Flex Home y Cápsula Linvig) en nuestro **Showroom Presencial de Armenia**.\n\n"
                            "📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n"
                            "🗓️ **Fechas de exhibición**: Martes 28 y Miércoles 29 de Julio (10:00 AM a 6:00 PM).\n\n"
                            "¿Te agendamos tu cupo de visita presencial en la **mañana** (10:00 AM - 12:00 PM) o en la **tarde** (2:00 PM - 5:30 PM)?"
                        )
                    }

            # PASO 1: Selección de Día por el Cliente (Martes 28 o Miércoles 29)
            has_both_days = any(w in msg_lower for w in ["28 y 29", "28 o 29", "28 u 29", "28/29", "martes y miércoles", "martes o miércoles"])
            is_day_btn = "btn_day_mar28" in msg_lower or "btn_day_mie29" in msg_lower
            is_day_selection = not is_form_submission and (is_day_btn or (not has_both_days and any(w in msg_lower for w in ["mar28", "mie29", "martes", "miércoles", "miercoles", "miérc", "mierc", "28 de julio", "29 de julio", "28 julio", "29 julio", "el 28", "el 29", "día 28", "dia 28", "día 29", "dia 29"])))
            if is_day_selection and not any(w in msg_lower for w in ["11:30", "14:30", "02:30", "10:00", "16:00", "17:00", "btn_time_"]):
                selected_day_name = "Miércoles 29 de Julio" if any(w in msg_lower for w in ["mie29", "miércoles", "miercoles", "miérc", "mierc", "29"]) else "Martes 28 de Julio"
                target_day_num = 29 if "29" in selected_day_name else 28
                contact.scheduling_state = "AWAITING_TIME"
                contact.proposed_datetime = datetime(2026, 7, target_day_num, 10, 0, 0)
                db.add(contact)
                db.commit()
                return {"response": f"¡Excelente elección! Para tu atención presencial el **{selected_day_name}**, por favor selecciona la hora de tu preferencia:"}

            # ESTADO: AWAITING_CONFIRMATION o AWAITING_TIME o clic en botones de propuesta
            is_direct_confirm_btn = any(w in msg_lower for w in ["btn_confirm_slot", "btn_yes", "sí, confirmar", "si, confirmar", "✅ sí, confirmar", "confirmo mi hora", "confirmar mi cita"])
            is_direct_change_btn = any(w in msg_lower for w in ["btn_change_slot", "btn_no", "btn_time_other", "cambiar hora", "📅 cambiar hora", "otra hora", "reprogramar", "otro horario"])

            if is_direct_change_btn:
                contact.scheduling_state = "AWAITING_CONFIRMATION"
                db.add(contact)
                db.commit()
                return {"response": "¡Con mucho gusto! Contamos también con los siguientes horarios disponibles para tu atención personalizada en el Showroom de Armenia:\n\n• **10:00 AM**\n• **04:00 PM**\n• **05:00 PM**\n\n¿Cuál de estos tres te queda mejor?"}

            if contact.scheduling_state in ["AWAITING_CONFIRMATION", "AWAITING_TIME"] or is_direct_confirm_btn or any(w in msg_lower for w in ["mañana", "tarde", "10", "11", "2", "3", "4", "5", "am", "pm"]):
                text_clean = re.sub(r'[^\w\s]', '', msg_lower)
                words_in_text = text_clean.split()
                
                confirm_words = ["si", "sí", "perfecto", "confirmado", "ok", "listo", "claro", "dale", "bueno", "super", "bien", "sirve", "asistir", "pendiente", "confirmo", "confirmar", "gracias", "muchas gracias", "gracia", "gracias!", "virtual", "presencial", "martes", "miércoles", "miercoles", "jueves", "30", "11:30", "02:30", "03:30", "04:00", "10:00", "09:00", "12:00", "14:00", "14:30", "15:30", "05:00", "17:00", "5:00", "02:00", "2:00", "16:00", "4:00", "btn_time_"]
                reject_words = ["no", "otro", "cambiar", "diferente", "no puedo", "no me queda", "ocupado", "reprogramar", "cancelar", "ninguno", "rechazar"]
                
                is_reject = any(w in words_in_text for w in reject_words) or "no puedo" in msg_lower or "otro dia" in msg_lower or "otra hora" in msg_lower
                if is_reject and not is_direct_confirm_btn:
                    contact.scheduling_state = "AWAITING_CONFIRMATION"
                    db.add(contact)
                    db.commit()
                    return {"response": "¡Con mucho gusto! Contamos también con los siguientes horarios disponibles para tu atención personalizada en el Showroom de Armenia:\n\n• **10:00 AM**\n• **04:00 PM**\n• **05:00 PM**\n\n¿Cuál de estos tres te queda mejor?"}

                # Detección adicional de horas y jornadas para confirmación automática
                time_phrases = ["10", "11", "12", "mañana", "tarde", "10am", "10 am", "11am", "11 am", "4pm", "4 pm", "5pm", "5 pm", "10:00", "16:00", "17:00", "04:00", "05:00", "a las", "las 10", "las 4", "las 5", "la mañana", "la tarde"]
                has_time_phrase = any(tp in msg_lower for tp in time_phrases) or any(w in words_in_text for w in ["am", "pm", "2pm", "3pm", "4pm", "5pm", "10am", "11am"])

                is_confirm = is_direct_confirm_btn or "btn_time_" in msg_lower or any(w in words_in_text or w in msg_lower for w in confirm_words) or has_time_phrase or "esta bien" in msg_lower or "de acuerdo" in msg_lower or "me sirve" in msg_lower or "estoy pendiente" in msg_lower or "de su llamada" in msg_lower or "gracias" in msg_lower
                
                if is_confirm:
                    # SUPERVISOR AUTO-PARSER DE HORA Y DÍA
                    if is_virtual_lead:
                        target_day = 30
                        if any(w in msg_lower for w in ["31", "viernes", "vie"]):
                            target_day = 31
                    else:
                        target_day = contact.proposed_datetime.day if contact.proposed_datetime else 28
                        if any(w in msg_lower for w in ["29", "miercoles", "miércoles", "mie", "btn_pres_mie"]):
                            target_day = 29
                        elif any(w in msg_lower for w in ["28", "martes", "mar", "btn_pres_mar"]):
                            target_day = 28
                    
                    target_hour = contact.proposed_datetime.hour if contact.proposed_datetime else 17
                    target_minute = contact.proposed_datetime.minute if contact.proposed_datetime else 0

                    if any(w in msg_lower for w in ["17:00", "05:00", "5:00", "5 pm", "5pm", "5 p.m", "btn_time_1700"]):
                        target_hour = 17
                        target_minute = 0
                    elif any(w in msg_lower for w in ["15:00", "03:00", "3:00", "3 pm", "3pm", "3 p.m"]):
                        target_hour = 15
                        target_minute = 0
                    elif any(w in msg_lower for w in ["16:00", "04:00", "4:00", "4 pm", "4pm", "btn_time_1600"]):
                        target_hour = 16
                        target_minute = 0
                    elif any(w in msg_lower for w in ["11:30", "11.30", "11:30am", "11:30 am", "1130"]):
                        target_hour = 11
                        target_minute = 30
                    elif any(w in msg_lower for w in ["14:30", "02:30", "2:30", "btn_time_1430", "btn_jl_mar_1430"]):
                        target_hour = 14
                        target_minute = 30
                    elif any(w in msg_lower for w in ["10:00", "10.00", "10:00am", "10:00 am", "10 am", "10am", "btn_time_1000"]):
                        target_hour = 10
                        target_minute = 0
                    
                    contact.proposed_datetime = datetime(2026, 7, target_day, target_hour, target_minute, 0)
                    db.add(contact)
                    db.commit()

                    if contact.proposed_datetime:
                        user_id = contact.assigned_user_id or 1
                        
                        appointment = Appointment(
                            contact_id=contact.id,
                            user_id=user_id,
                            datetime=contact.proposed_datetime,
                            status="CONFIRMED",
                            notes="Agendado automáticamente por el flujo multi-agente de ANCLA."
                        )
                        db.add(appointment)

                        from app.services.activity import record_activity
                        record_activity(
                            db=db,
                            contact_id=contact.id,
                            activity_type="appointment_booked",
                            description=f"Cita comercial agendada automáticamente por Sofi para {appointment.datetime.strftime('%Y-%m-%d %I:%M %p')}.",
                            user_id=user_id
                        )

                        # Mover lead en Kanban
                        stages = db.query(PipelineStage).all()
                        stage_by_name = {s.name: s.id for s in stages}
                        llamada_agendada_id = stage_by_name.get("Llamada Agendada")
                        if llamada_agendada_id:
                            contact.pipeline_stage_id = llamada_agendada_id
                            db.add(contact)

                        # Integración con Google Workspace
                        from app.services.google_integration import create_google_calendar_event, upload_lead_report_to_google_drive
                        try:
                            await create_google_calendar_event(db, appointment, contact)
                            await upload_lead_report_to_google_drive(db, contact, appointment)
                        except Exception as ge:
                            logger.error(f"Error sincronizando con Google en LangGraph appointments: {ge}")

                        # Formatear fecha
                        formatted_date = appointment.datetime.strftime("%A %d de %B a las %I:%M %p")
                        day_translations = {
                            "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
                            "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
                            "January": "Enero", "February": "Febrero", "March": "Marzo", "April": "Abril",
                            "May": "Mayo", "June": "Junio", "July": "Julio", "August": "Agosto",
                            "September": "Septiembre", "October": "Octubre", "November": "Noviembre", "December": "Diciembre"
                        }
                        for en, es in day_translations.items():
                            formatted_date = formatted_date.replace(en, es)

                        # Emitir por WS
                        from app.core.socket_manager import manager
                        ws_payload = {
                            "event": "appointment_created",
                            "data": {
                                "id": appointment.id,
                                "contact_id": contact.id,
                                "user_id": user_id,
                                "datetime": appointment.datetime.isoformat(),
                                "contact_name": f"{contact.first_name or ''} {contact.last_name or ''}".strip() or contact.phone,
                                "pipeline_stage_id": contact.pipeline_stage_id
                            }
                        }
                        await manager.broadcast(ws_payload)

                        c_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or "estimado/a cliente"
                        c_email = contact.email or "tu correo electrónico"
                        is_virt = any(w in msg_lower for w in ["virtual", "videollamada", "meet", "llamada"])
                        modality_name = "Asesoría Virtual por Llamada" if is_virt else "Visita Presencial al Showroom"
                        modality_detail = "Llamada directa al celular / Google Meet" if is_virt else "Atención Presencial en Showroom de Armenia"
                        
                        date_str = appointment.datetime.strftime("%A %d de %B").title()
                        time_str = appointment.datetime.strftime("%I:%M %p")
                        for en, es in [("Monday","Lunes"),("Tuesday","Martes"),("Wednesday","Miércoles"),("Thursday","Jueves"),("Friday","Viernes"),("January","Enero"),("February","Febrero"),("March","Marzo"),("April","Abril"),("May","Mayo"),("June","Junio"),("July","Julio"),("August","Agosto")]:
                            date_str = date_str.replace(en, es)

                        if is_virt:
                            email_line = f"📧 **Correo**: {contact.email}\n" if contact.email else ""
                            phone_line = f"📱 **Teléfono de atención**: Te llamaremos a tu WhatsApp ({contact.phone}).\n"
                            link_line = "🔗 **Enlace de Conexión**: En las próximas horas nuestro **asesor especialista en proyectos modulares** te enviará por este mismo chat el enlace de conexión (Google Meet / Llamada) para nuestra reunión.\n"
                            detail_block = f"{phone_line}{email_line}{link_line}"
                        else:
                            email_line = f"📧 **Correo**: {contact.email or 'Registrado en sistema'}\n"
                            loc_line = "📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n"
                            detail_block = f"{email_line}{loc_line}"

                        response_text = (
                            f"¡Excelente noticia, {c_name}! 🗓️✨\n\n"
                            f"Tu **{modality_name}** está 100% PROGRAMADA. A continuación encuentras el resumen de tu reserva:\n\n"
                            f"👤 **Nombre**: {c_name}\n"
                            f"📞 **Modalidad**: {modality_detail}\n"
                            f"📅 **Fecha**: {date_str}\n"
                            f"⏰ **Hora**: {time_str}\n"
                            f"{detail_block}\n"
                            f"¿Tienes alguna pregunta o inquietud adicional sobre tu proyecto antes de nuestro encuentro? 💬✨\n\n"
                            f"Si todo está claro por ahora, ¡te agradecemos inmensamente tu interés y quedamos muy atentos para atenderte! 🏡🤝"
                        )

                        # Enviar notificación oficial de confirmación completa a los WhatsApps administrativos (Liliana + Diego)
                        try:
                            admin_phones = ["573202876282", "573177001670"]
                            full_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or "Cliente"
                            email_str = contact.email or "No provisto"
                            phone_str = f"+{contact.phone}" if not contact.phone.startswith("+") else contact.phone
                            form_msg = db.query(Message).filter(Message.contact_id == contact.id, Message.content.ilike("%completé el formulario%")).first()
                            if form_msg and form_msg.content:
                                lines = [l.strip() for l in form_msg.content.split("\n") if l.strip() and not l.strip().startswith("¡Hola!") and not l.strip().startswith("Full name:") and not l.strip().startswith("Phone number:")]
                                notes_clean = "\n".join(lines)
                            else:
                                notes_clean = contact.qualification_notes or "Cita agendada automáticamente por Sofi vía WhatsApp."
                                if "[Meta Ads" in notes_clean:
                                    notes_clean = "Lead registrado en campaña Meta Ads (Showroom Armenia)."

                            confirmed_report = (
                                f"📋 **RESUMEN DE CITA CONFIRMADA (ANCLA SPECIAL PROJECTS)** 📋\n\n"
                                f"• **Nombre**: {full_name}\n"
                                f"• **Teléfono**: {phone_str}\n"
                                f"• **Correo**: {email_str}\n"
                                f"• **Perfil / Proyecto**: Cliente Calificado con Cita Confirmada\n"
                                f"• **Cita Programada**: {date_str} a las {time_str}\n"
                                f"• **Modalidad**: {modality_detail}\n\n"
                                f"💬 **HISTORIAL Y DETALLES DEL REGISTRO**:\n"
                                f"{full_name} seleccionó y confirmó su espacio para {date_str} a las {time_str}.\n\n"
                                f"📝 **Ficha Técnica / Preguntas del Formulario**:\n"
                                f"{notes_clean}"
                            )
                            from app.services.whatsapp import whatsapp_service
                            for phone in admin_phones:
                                await whatsapp_service.send_text_message(to_phone=phone, message_text=confirmed_report, db=db)
                        except Exception as e_adm:
                            logger.error(f"Error enviando reporte de cita confirmada a administradores: {e_adm}")

                        # Resetear memoria de cita
                        contact.scheduling_state = None
                        contact.proposed_datetime = None
                        db.add(contact)
                        db.commit()

                        return {"response": response_text}
                
                elif is_reject or any(w in msg_lower for w in ["otra hora", "otro horario", "btn_time_other", "cambiar hora"]):
                    contact.scheduling_state = "AWAITING_CONFIRMATION"
                    db.add(contact)
                    db.commit()
                    return {"response": "¡Con mucho gusto! Contamos también con los siguientes horarios disponibles para tu atención personalizada en el Showroom de Armenia:\n\n• **10:00 AM**\n• **04:00 PM**\n• **05:00 PM**\n\n¿Cuál de estos tres te queda mejor?"}
                
                else:
                    # El cliente hizo una pregunta o aportó información no relacionada
                    logger.info(f"Sofi: Cliente hizo pregunta general en confirmación: '{msg}'. Respondiendo limpiamente.")
                    temp_state = state.copy()
                    
                    if any(w in msg_lower for w in ["ubicacion", "ubicación", "showroom", "direccion", "dirección", "inauguracion", "inauguración", "evento", "donde"]):
                        temp_res = await info_agent_node(temp_state)
                    else:
                        temp_res = await sales_agent_node(temp_state)
                        
                    answer = temp_res.get("response", "")
                    return {"response": answer}

            # ESTADO: AWAITING_PREFERENCE
            elif contact.scheduling_state == "AWAITING_PREFERENCE":
                day_pref = None
                for d in ["lunes", "martes", "miercoles", "miércoles", "jueves", "viernes", "sabado", "sábado", "domingo"]:
                    if d in msg_lower:
                        day_pref = d
                        break
                
                time_pref = None
                if "mañana" in msg_lower or "temprano" in msg_lower or "am" in msg_lower:
                    time_pref = "mañana"
                elif "tarde" in msg_lower or "noche" in msg_lower or "pm" in msg_lower:
                    time_pref = "tarde"

                slot_formateado, slot_dt = await self._get_first_available_slot(db, contact, day_pref, time_pref)
                if slot_dt:
                    contact.scheduling_state = "AWAITING_CONFIRMATION"
                    contact.proposed_datetime = slot_dt
                    db.add(contact)
                    db.commit()
                    return {"response": f"Perfecto. Encontré disponible el {slot_formateado}. ¿Te queda bien ese horario para agendar la llamada?"}
                else:
                    slot_formateado_global, slot_dt_global = await self._get_first_available_slot(db, contact)
                    if slot_dt_global:
                        contact.scheduling_state = "AWAITING_CONFIRMATION"
                        contact.proposed_datetime = slot_dt_global
                        db.add(contact)
                        db.commit()
                        return {"response": f"No tengo horas disponibles que coincidan exactamente con tu preferencia de horario, pero tengo libre el {slot_formateado_global}. ¿Te viene bien esa hora?"}
                    else:
                        return {"response": "Por el momento tengo la agenda llena. Déjanos tu correo y un asesor te contactará a la brevedad."}

            return {"response": "Lo siento, ¿podrías indicarme qué día de la semana prefieres para nuestra llamada?"}

        async def info_agent_node(state: AgentState) -> dict:
            """
            Agente Informativo: Muestra la ubicación, modelos e invita de inmediato a agendar la asesoría/cita. (Temp 0.1)
            """
            db = state["db"]
            contact = state["contact"]
            msg_lower = state["last_message"].lower().strip()
            
            # Buscar si el cliente ya tiene una cita de asesoría confirmada
            from app.models.base import Appointment
            existing_app = db.query(Appointment).filter(
                Appointment.contact_id == contact.id,
                Appointment.status == "CONFIRMED"
            ).order_by(Appointment.created_at.desc()).first()
            
            if existing_app:
                date_str = existing_app.datetime.strftime("%A %d de %B a las %I:%M %p")
                day_translations = {
                    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
                    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
                    "January": "Enero", "February": "Febrero", "March": "Marzo", "April": "Abril",
                    "May": "Mayo", "June": "Junio", "July": "Julio", "August": "Agosto",
                    "September": "Septiembre", "October": "Octubre", "November": "Noviembre", "December": "Diciembre"
                }
                for en, es in day_translations.items():
                    date_str = date_str.replace(en, es)
                
                appt_reminder = f"\n\n🔔 **Recordatorio de tu Cita**: Recuerda que ya tenemos programada tu **Asesoría Virtual** para el **{date_str}**. ¡Nuestro asesor especialista se comunicará directamente contigo!"
            else:
                appt_reminder = ""

            # Ubicación / Showroom
            if any(w in msg_lower for w in ["ubicacion", "ubicación", "showroom", "direccion", "dirección", "/ubicacion"]):
                if existing_app:
                    return {
                        "response": f"📍 **UBICACIÓN SHOWROOM — ANCLA SPECIAL PROJECTS**\n\nNos encontramos en **Armenia, Quindío — Avenida Centenario, frente a Pan y Miel**.\n⏰ Horario de Atención: Lunes a Sábado (9:00 AM a 5:00 PM).{appt_reminder}"
                    }
                else:
                    return {
                        "response": "📍 **UBICACIÓN SHOWROOM — ANCLA SPECIAL PROJECTS**\n\nNos encontramos en **Armenia, Quindío — Avenida Centenario, frente a Pan y Miel**.\n⏰ Atención en el evento: Martes 28 y Miércoles 29 de Julio (10:00 AM a 5:00 PM).\n\n¿Te gustaría agendar tu cupo presencial para asistir este 28 o 29 de Julio?"
                    }
            # Inauguración
            elif any(w in msg_lower for w in ["inauguracion", "inauguración", "evento", "/inauguracion"]):
                if existing_app:
                    return {
                        "response": f"🏛️ **GRAN INAUGURACIÓN SHOWROOM ARMENIA**\n\n📅 **Fechas**: Martes 28 y Miércoles 29 de Julio (10:00 AM a 5:00 PM)\n📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.{appt_reminder}"
                    }
                else:
                    return {
                        "response": "🏛️ **GRAN INAUGURACIÓN SHOWROOM ARMENIA**\n\n📅 **Fechas**: Martes 28 y Miércoles 29 de Julio (10:00 AM a 5:00 PM)\n📍 **Ubicación**: Armenia, Quindío — Avenida Centenario, frente a Pan y Miel.\n\n¿Deseas agendar tu hora de visita presencial para garantizar tu atención personalizada?"
                    }
            # Modelos del catálogo
            else:
                if existing_app:
                    return {
                        "response": (
                            f"🏠 **CASAS MODULARES ANCLA (Flex Home, Cápsula Linvig & Cuartos Fríos)**\n\n"
                            f"Contamos con modelos modulares personalizables de 36m², 56m² y 72m² en estructura de acero galvanizado y aislamiento termoacústico de alto nivel:\n\n"
                            f"• **Flex Home (36m², 56m² y 72m²)**: Casas modulares expandibles de 1, 2 y 3 habitaciones.\n"
                            f"• **Cápsula Linvig (13m²)**: Suite/cabina premium ideal para proyectos de turismo o glamping.\n"
                            f"• **Cuartos Fríos**: Soluciones industriales de conservación o congelación.\n"
                            f"• **Proyectos a la Medida**: Diseños personalizados llave en mano para tu terreno.\n\n"
                            f"Como tu cita ya está programada, en nuestra sesión revisaremos a fondo el catálogo completo con fotos, planos de distribución y resolveremos todas tus dudas técnicas.{appt_reminder}"
                        )
                    }
                else:
                    return {
                        "response": "🏠 **CASAS MODULARES ANCLA (Flex Home, Cápsula Linvig & Cuartos Fríos)**\n\nContamos con modelos modulares personalizables de 36m², 56m² y 72m² en estructura de acero galvanizado y aislamiento termoacústico de alto nivel.\n\n💡 *Como cada proyecto se adapta a tu terreno y ubicación*, entregamos los costos exactos y asesoría técnica en una breve llamada de 15 min o visita al Showroom de Armenia (28 u 29 de Julio).\n\n¿Te agendamos un cupo en la mañana o en la tarde?"
                    }

        async def sales_agent_node(state: AgentState) -> dict:
            """
            Agente de Ventas / Consultoría RAG: Contesta con el catálogo e información contextual. (Temp 0.6)
            """
            db = state["db"]
            contact = state["contact"]
            last_message = state["last_message"]

            # Cargar prompts
            prompt_setting = db.query(SystemSetting).filter(SystemSetting.key == "chatbot_prompt").first()
            system_instruction = prompt_setting.value if prompt_setting else (
                "Eres un asistente de ventas de IA experto para ANCLA Special Projects. "
                "Tu objetivo es resolver dudas técnicas de forma amable, clara y persuasiva, "
                "y guiar al prospecto calificado a agendar una breve sesión/llamada informativa."
            )

            # Inyección de reglas de negocio
            system_instruction += (
                "\n\n[REGLAS E INSTRUCCIONES DE VENTA OBLIGATORIAS (ANCLA SPECIAL PROJECTS)]:\n"
                "1. POLÍTICA ESTRICTA DE CERO PRECIOS: Bajo NINGUNA circunstancia des precios numéricos, valores o cotizaciones por chat. Explica amablemente que se calculan en una breve sesión técnica de Meet de 10 minutos.\n"
                "2. POLÍTICA ESTRICTA DE CERO LINKS/ENLACES EXTERNOS: Bajo NINGUNA circunstancia envíes enlaces, URLs (como anclaspecialprojects.com/agendar), ni links de agendas externas. El agendamiento o reprogramación se realiza 100% de forma conversacional en el chat preguntando qué día de la semana y qué hora le conviene al cliente.\n"
                "3. REGLA DE HUMANIZACIÓN Y NOMBRE: NUNCA repitas el nombre del cliente en cada mensaje consecutivo. Si ya se usó su nombre en mensajes anteriores del mismo día, NO lo vuelvas a incluir al inicio de cada frase. Habla de forma natural y fluida como un consultor humano real.\n"
                "4. OBJETIVO PRINCIPAL: Guiar al cliente calificado a agendar una llamada por Meet/teléfono ofreciendo horarios específicos con botones de opción.\n"
                "5. CALIFICACIÓN DEL LEAD: Tu objetivo secundario es indagar amablemente sobre el lote/terreno, la ubicación del proyecto, o temperaturas/especificaciones en cuartos fríos.\n"
                "6. TONO: Profesional, consultivo, sumamente educado y centrado en la excelencia técnica.\n"
                "7. CIERRE CON INVITACIÓN AL SHOWROOM/ASESORÍA: Tras responder la consulta técnica (materiales, estructura, aislamiento), invita al cliente a conocer las muestras físicas y fichas en el Showroom de Armenia (28 y 29 de Julio) o en su Asesoría Virtual (a partir del 30 de Julio)."
            )

            # RAG Vectorial con Búsqueda Híbrida y RRF
            try:
                from app.services.rag_service import search_hybrid_knowledge
                relevant_chunks = await search_hybrid_knowledge(last_message, db, limit=4)
                if relevant_chunks:
                    rag_context = "\n\n".join([f"--- Fragmento de base de conocimiento ---\n{c}" for c in relevant_chunks])
                    system_instruction += (
                        f"\n\n[INFORMACIÓN OFICIAL Y RESPUESTAS DE LA EMPRESA (BASE DE CONOCIMIENTO)]:\n"
                        f"Usa los siguientes datos e información oficial para contestar con total precisión. "
                        f"Si el cliente te pregunta algo sobre los siguientes temas, responde strictly en base a este conocimiento:\n\n"
                        f"{rag_context}"
                    )
            except Exception as e_rag:
                logger.error(f"Error recuperando contexto de RAG vectorial en LangGraph: {e_rag}")

            # Inyección de Aprendizaje Continuo (Correcciones Aprobadas por Asesores - Few-Shot Learning)
            try:
                from app.models.base import AuditCorrection
                recent_corrections = db.query(AuditCorrection).filter(AuditCorrection.is_approved == True).order_by(AuditCorrection.created_at.desc()).limit(5).all()
                if recent_corrections:
                    few_shot_examples = "\n".join([
                        f"• Pregunta/Mensaje del Cliente: \"{c.query}\"\n  Respuesta Ideal Aprobada por Asesor: \"{c.corrected_response}\""
                        for c in recent_corrections
                    ])
                    system_instruction += (
                        f"\n\n[APRENDIZAJE CONTINUO - RESPUESTAS MODELO APORTADAS Y CORREGIDAS POR ASESORES EXPERTOS]:\n"
                        f"Toma como máxima referencia de tono y criterio comercial estas respuestas reales corregidas por los asesores humanos:\n\n"
                        f"{few_shot_examples}"
                    )
            except Exception as e_corr:
                logger.error(f"Error recuperando correcciones de aprendizaje humano: {e_corr}")

            # Calificar lead en paralelo
            try:
                from app.services.qualification import analyze_and_qualify_lead
                analyze_and_qualify_lead(db, contact, last_message)
            except Exception:
                pass

            # Cargar historial
            from app.models.base import Message as DBMessage, SenderType
            past_msgs = db.query(DBMessage).filter(DBMessage.contact_id == contact.id).order_by(DBMessage.created_at.desc()).limit(15).all()
            past_msgs.reverse()

            time_greeting_rule = "CONVERSACIÓN ACTIVA DEL MISMO DÍA (MENOS DE 24 HORAS). PROHIBIDO volver a decir 'Hola' o saludar. Responde directo a la duda sin preámbulos."
            if past_msgs:
                last_msg_time = past_msgs[-1].created_at
                hours_diff = (datetime.now() - last_msg_time).total_seconds() / 3600.0
                if hours_diff > 18:
                    time_greeting_rule = "HAN PASADO MÁS DE 18-24 HORAS (NUEVO DÍA). Saluda cordialmente ('¡Hola nuevamente!') antes de responder."

            history_lines = []
            for m in past_msgs:
                sender = "Cliente" if m.sender_type == SenderType.CONTACT else ("Sofi (IA)" if m.sender_type == SenderType.AI else "Asesor")
                history_lines.append(f"{sender}: {m.content}")

            history_context = "\n".join(history_lines) if history_lines else f"Cliente: {last_message}"

            prompt = (
                f"HISTORIAL DE CONVERSACIÓN RECIENTE CON EL CLIENTE '{contact.first_name or 'cliente'}':\n"
                f"{history_context}\n\n"
                f"ÚLTIMO MENSAJE RECIBIDO DEL CLIENTE: '{last_message}'\n\n"
                f"REGLAS OBLIGATORIAS DE RESPUESTA DIRECTA Y CONTINUIDAD (ANCLA SPECIAL PROJECTS):\n"
                f"1. REGLA DE SALUDO: {time_greeting_rule}\n"
                f"2. RESPUESTA DIRECTA AL GRANO: Responde la duda exacta desde la primera palabra. Cero preámbulos.\n"
                f"3. EFICIENCIA: Máximo 2 a 3 frases cortas por mensaje.\n"
                f"4. CERO PRECIOS NUMÉRICOS: Jamás entregues cifras.\n"
                f"5. PREGUNTA FINAL CONSULTIVA: Cierra con una pregunta breve sobre su proyecto."
            )

            api_key = self._get_api_key(db) or settings.GEMINI_API_KEY
            reply = await self._call_llm(api_key, system_instruction, prompt, temperature=0.6) # Flujo fluido
            sanitized_reply = await self._sanitize_and_enforce_rules(reply, db)
            return {"response": sanitized_reply}

        # --- ORQUESTACIÓN DEL FLUJO CON LANGGRAPH ---

        workflow = StateGraph(AgentState)

        workflow.add_node("orquestador", orchestrator_node)
        workflow.add_node("citas", appointments_agent_node)
        workflow.add_node("ventas", sales_agent_node)
        workflow.add_node("informativo", info_agent_node)

        workflow.set_entry_point("orquestador")

        def route_orchestrator(state: AgentState):
            return state["next_node"]

        workflow.add_conditional_edges(
            "orquestador",
            route_orchestrator,
            {
                "citas": "citas",
                "ventas": "ventas",
                "informativo": "informativo",
                "end": END
            }
        )

        workflow.add_edge("citas", END)
        workflow.add_edge("ventas", END)
        workflow.add_edge("informativo", END)

        app_graph = workflow.compile()

        # Invocar la ejecución del grafo
        initial_state = {
            "db": db,
            "contact": contact,
            "last_message": last_message,
            "next_node": "",
            "response": None
        }

        try:
            from app.services.activity import record_activity
            result = await app_graph.ainvoke(initial_state)
            resp = result.get("response")
            if resp:
                record_activity(db, contact.id, "ai_response_generated", f"Sofi: Generada respuesta de la IA: '{resp[:120]}...'")
            else:
                record_activity(db, contact.id, "ai_no_response", "Sofi: La ejecución del grafo de agentes terminó sin una respuesta.")
            return resp
        except Exception as e_graph:
            logger.error(f"Error ejecutando grafo LangGraph de Sofi: {e_graph}")
            from app.services.activity import record_activity
            record_activity(db, contact.id, "ai_error", f"Sofi: Fallo en ejecución de grafo: {str(e_graph)[:120]}")
            # Fallback seguro a las heurísticas de autopiloto tradicional en caso de fallo
            fallback_reply = self._heuristic_autopilot(contact, last_message)
            sanitized = await self._sanitize_and_enforce_rules(fallback_reply, db)
            record_activity(db, contact.id, "ai_response_generated", f"Sofi: Usando respuesta de contingencia (fallback): '{sanitized[:120]}...'")
            return sanitized

    async def _run_llm_guardrails(self, reply: str, db: Session) -> str:
        """
        Aplica un guardrail conversacional por LLM (temperatura 0.0) para evaluar la respuesta generada.
        Si detecta precios numéricos u cotizaciones directas prohibidas, reescribe el texto amigablemente.
        """
        api_key = self._get_api_key(db) or settings.GEMINI_API_KEY
        if not api_key:
            return reply
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        is_openrouter = api_key.startswith("sk-or-v1")
        if is_openrouter:
            url = "https://openrouter.ai/api/v1/chat/completions"

        system_instruction = (
            "Actúas como un Auditor de Cumplimiento Comercial y de Marca estricto para ANCLA Special Projects.\n"
            "Tu misión es garantizar la POLÍTICA DE CERO PRECIOS y CERO ENLACES EXTERNOS en WhatsApp.\n"
            "Reglas de auditoría:\n"
            "1. CERO PRECIOS: Si la respuesta contiene precios numéricos directos, cotizaciones o valores (ej: '$85,000,000', '15 mil dólares'), REESCRIBE la respuesta eliminando los precios. Explica que se calculan en una breve llamada técnica de 10 minutos por Meet.\n"
            "2. CERO ENLACES EXTERNOS: Si la respuesta contiene URLs, links, enlaces (como /agendar, http, o anclaspecialprojects.com), ELIMINA completamente el enlace y reemplázalo por: '¿Qué día de la semana y qué horario te convienen para coordinar tu llamada directamente por aquí?'\n"
            "3. Si la respuesta cumple todas las reglas, devuélvela EXACTAMENTE igual, sin cambiarle ni una sola palabra.\n"
            "4. Bajo ninguna circunstancia saludes o agregues preámbulos fuera de la respuesta del bot."
        )

        payload = {}
        if is_openrouter:
            payload = {
                "model": "google/gemini-2.5-flash",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": reply}
                ],
                "temperature": 0.0
            }
        else:
            payload = {
                "contents": [{"parts": [{"text": reply}]}],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "generationConfig": {"temperature": 0.0}
            }

        try:
            async with httpx.AsyncClient() as client:
                headers = {}
                if is_openrouter:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://anclaspecialprojects.com",
                        "X-Title": "ANCLA Special Projects CRM"
                    }
                res = await client.post(url, json=payload, headers=headers, timeout=6.0)
                if res.status_code == 200:
                    data = res.json()
                    guardrail_reply = ""
                    if is_openrouter:
                        guardrail_reply = data["choices"][0]["message"]["content"].strip()
                    else:
                        guardrail_reply = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if guardrail_reply:
                        logger.info("Guardrail conversacional por LLM ejecutado y validado con éxito.")
                        return guardrail_reply
        except Exception as e:
            logger.error(f"Error de conexión en guardrail LLM (se utilizará sanitización por regex): {e}")

        return reply

    async def _sanitize_and_enforce_rules(self, reply: str, db: Optional[Session] = None) -> str:
        if not reply:
            return reply

        # 0. Ejecutar Guardrail por LLM primero si hay base de datos disponible
        if db:
            reply = await self._run_llm_guardrails(reply, db)

        import re

        # 1. Remover Emojis Prohibidos (🤩, 😂, 🔥, 🙌, 💯, 🙈, 😜, 😎, 🥳, 😍)
        forbidden_emojis = ["🤩", "😂", "🔥", "🙌", "💯", "🙈", "😜", "😎", "🥳", "😍"]
        for fe in forbidden_emojis:
            reply = reply.replace(fe, "😊")

        # 2. Eliminar referencias a Instagram, redes sociales, @AnclaProjects o inventar usuarios de redes
        if any(w in reply.lower() for w in ["instagram", "anclaprojects", "redes sociales", "síguenos", "siguenos", "perfil"]):
            reply = re.sub(r'te invitamos a visitar nuestro perfil de Instagram [^\n\.]*', 'con gusto te enviamos fotos y renders directamente por este chat de WhatsApp o te los mostramos en nuestra videollamada por Meet.', reply, flags=re.IGNORECASE)
            reply = re.sub(r'@[A-Za-z0-9_]+', '', reply)

        # 3. Eliminar enlaces externos de agendamiento
        reply = re.sub(r'https?://[^\s]+', '', reply).strip()
        reply = re.sub(r'(?:puedes seleccionar|puedes ingresar|puedes ingresar a|a través de|en el siguiente|mediante este|en este)\s+(?:el horario que mejor te convenga a través de|este|el|nuestro)?\s*(?:enlace directo|enlace|link|calendario)[:\s]*', 'con gusto lo coordinamos directamente por aquí. ', reply, flags=re.IGNORECASE)
        reply = re.sub(r'https?://[^\s]+', '', reply).strip()
        reply = re.sub(r'\s{2,}', ' ', reply)

        # 4. CONTRATO INVIOLABLE DE SOFI: Reemplazar cualquier confirmación informal por la Plantilla Oficial Ejecutiva
        if any(phrase in reply.lower() for phrase in ["ya agendamos tu cita", "cita agendada", "recibirás un correo de confirmación", "cita virtual para el"]):
            c_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() if contact else "estimado/a cliente"
            c_email = (contact.email if contact and contact.email else "tu correo electrónico")
            date_str = contact.proposed_datetime.strftime("%A %d de %B").title() if (contact and contact.proposed_datetime) else "Martes 28 de Julio"
            time_str = contact.proposed_datetime.strftime("%I:%M %p") if (contact and contact.proposed_datetime) else "10:00 AM"
            for en, es in [("Monday","Lunes"),("Tuesday","Martes"),("Wednesday","Miércoles"),("Thursday","Jueves"),("Friday","Viernes"),("July","Julio")]:
                date_str = date_str.replace(en, es)
                
            reply = (
                f"¡Excelente noticia, {c_name}! 🗓️✨\n\n"
                f"Tu **Asesoría Virtual** está 100% PROGRAMADA. A continuación encuentras el resumen de tu reserva:\n\n"
                f"👤 **Nombre**: {c_name}\n"
                f"✉️ **Correo**: {c_email}\n"
                f"📞 **Modalidad**: Asesoría Virtual (Llamada a celular 📞 / Google Meet 💻)\n"
                f"📅 **Fecha**: {date_str}\n"
                f"⏰ **Hora**: {time_str}\n\n"
                f"¿Tienes alguna pregunta o inquietud adicional sobre tu proyecto antes de nuestro encuentro? 💬✨\n\n"
                f"Si todo está claro por ahora, ¡te agradecemos inmensamente tu interés y quedamos muy atentos para atenderte! 🏡🤝"
            )

        # 4. Sustituir manuales técnicos pesados por frases comerciales atractivas
        technical_jargon = {
            "perfiles de acero de alta especificación ASTM A36": "estructura de alta resistencia",
            "paneles sándwich de poliuretano inyectado de 50mm": "aislamiento termoacústico de alto confort",
            "pisos vinílicos SPC de tráfico pesado": "acabados elegantes y duraderos"
        }
        for tj, replacement in technical_jargon.items():
            reply = reply.replace(tj, replacement)

        return reply

    async def generate_ad_copy(self, product_description: str, tone: str, db: Session = None) -> Dict[str, Any]:
        """
        Genera copys de publicidad usando Google Gemini.
        """
        api_key = self.api_key
        if db:
            api_key = self._get_api_key(db)

        if not api_key:
            return self._heuristic_ad_copy(product_description, tone)

        url = f"{self.api_url}?key={api_key}"
        
        system_instruction = (
            "Eres un copywriter experto en Meta Ads. Genera un copy publicitario atractivo. "
            "Debes estructurar tu respuesta EXCLUSIVAMENTE en formato JSON con los campos exactos: "
            "headline, body, cta. No agregues nada de texto antes o después del JSON."
        )

        prompt = f"Producto/servicio: '{product_description}'. Tono comercial: '{tone}'."

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "systemInstruction": {
                "parts": [
                    {"text": system_instruction}
                ]
            },
            "generationConfig": {
                "temperature": 0.8,
                "responseMimeType": "application/json"
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=15.0)
                if response.status_code == 200:
                    import json
                    data = response.json()
                    raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    return json.loads(raw_text)
                else:
                    return self._heuristic_ad_copy(product_description, tone)
        except Exception as e:
            logger.error(f"Error en Gemini Copywriter: {e}")
            return self._heuristic_ad_copy(product_description, tone)

    # --- Lógica Interna de Disponibilidad ---

    async def _get_first_available_slot(
        self, 
        db: Session, 
        contact: Contact, 
        day_pref: str = None, 
        time_pref: str = None
    ) -> tuple:
        user_id = contact.assigned_user_id or 1
        
        from app.models.base import User, UserRole
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            user = db.query(User).first()
            if not user:
                user = User(
                    email="admin@anclaspecialprojects.com",
                    hashed_password="adminpassword",
                    full_name="Asesor Principal ANCLA",
                    role=UserRole.ADMIN,
                    is_active=True
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            user_id = user.id
        
        availabilities = db.query(Availability).filter(Availability.user_id == user_id).all()
        if not availabilities:
            for day in range(5):
                av = Availability(
                    user_id=user_id,
                    day_of_week=day,
                    start_time=time(10, 0, 0),
                    end_time=time(17, 0, 0)
                )
                db.add(av)
            db.commit()
            availabilities = db.query(Availability).filter(Availability.user_id == user_id).all()

        avail_by_day = {av.day_of_week: av for av in availabilities}
        today = datetime.utcnow().date()
        
        # Iniciar la búsqueda el 28 de Julio de 2026 si hoy es una fecha anterior
        from datetime import date
        event_start_date = date(2026, 7, 28)
        search_start = event_start_date if today < event_start_date else today
        
        from collections import Counter
        appointments = db.query(Appointment).filter(
            Appointment.status == "CONFIRMED",
            Appointment.datetime >= datetime.combine(search_start, time.min)
        ).all()
        # Contar citas por hora exacta
        reserved_counts = Counter(app.datetime for app in appointments)

        target_day_num = None
        if day_pref:
            day_map = {
                "lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2,
                "jueves": 3, "viernes": 4, "sabado": 5, "sábado": 5, "domingo": 6,
                "28": 1, "29": 2, "30": 3  # Jueves 30 de Julio
            }
            for k, v in day_map.items():
                if k in day_pref.lower():
                    target_day_num = v
                    break

        # Extraer hora específica deseada (ej. 10, 11, 12, 2, 3, 4, 10:30, 2:30)
        target_hour = None
        target_minute = 0
        if time_pref:
            import re
            time_match = re.search(r'\b(10|11|12|1|2|3|4|5)(?::(30|00))?\s*(am|pm)?\b', time_pref.lower())
            if time_match:
                h = int(time_match.group(1))
                m = int(time_match.group(2)) if time_match.group(2) else 0
                meridiem = time_match.group(3)
                if meridiem == "pm" and h < 12:
                    h += 12
                elif meridiem == "am" and h == 12:
                    h = 0
                elif not meridiem:
                    if h in [1, 2, 3, 4, 5]:
                        h += 12 # Asumir PM para 1, 2, 3, 4, 5 de la tarde
                target_hour = h
                target_minute = m

        # Determinar límite de capacidad según modalidad (Virtual = 1, Presencial = 4)
        is_virtual = any(w in (day_pref or "").lower() or w in (time_pref or "").lower() for w in ["virtual", "videollamada", "meet", "llamada"])
        max_capacity = 1 if is_virtual else 4

        current_time = datetime.utcnow()
        for i in range(0, 14): # Buscar en un rango de 14 días
            day_date = search_start + timedelta(days=i)
            day_of_week = day_date.weekday()
            
            if target_day_num is not None and day_of_week != target_day_num:
                continue

            if target_day_num is None and day_of_week in [5, 6]:
                continue

            if day_of_week in avail_by_day:
                av = avail_by_day[day_of_week]
                start_dt = datetime.combine(day_date, time(10, 0, 0)) # Inicio 10:00 AM
                end_dt = datetime.combine(day_date, time(17, 0, 0))   # Cierre 05:00 PM
                
                temp_dt = start_dt
                while temp_dt + timedelta(minutes=30) <= end_dt:
                    hour = temp_dt.hour
                    minute = temp_dt.minute
                    
                    # DESCANSO OBLIGATORIO DE ALMUERZO: 1:00 PM a 2:00 PM (13:00 a 14:00)
                    if hour == 13:
                        temp_dt += timedelta(minutes=30)
                        continue

                    if target_hour is not None:
                        if hour != target_hour or (target_minute != 0 and minute != target_minute):
                            temp_dt += timedelta(minutes=30)
                            continue
                    elif time_pref:
                        if "mañana" in time_pref.lower() and hour >= 13:
                            temp_dt += timedelta(minutes=30)
                            continue
                        elif "tarde" in time_pref.lower() and hour < 12:
                            temp_dt += timedelta(minutes=30)
                            continue

                    # Verificar capacidad
                    current_booked = reserved_counts.get(temp_dt, 0)
                    if current_booked < max_capacity and temp_dt > current_time:
                        formatted = temp_dt.strftime("%A %d de %B a las %I:%M %p")
                        day_translations = {
                            "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
                            "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
                            "January": "Enero", "February": "Febrero", "March": "Marzo", "April": "Abril",
                            "May": "Mayo", "June": "Junio", "July": "Julio", "August": "Agosto",
                            "September": "Septiembre", "October": "Octubre", "November": "Noviembre", "December": "Diciembre"
                        }
                        for en, es in day_translations.items():
                            formatted = formatted.replace(en, es)
                        return formatted, temp_dt
                    temp_dt += timedelta(minutes=30)
        return None, None
        return None, None

    # --- Heurísticas / Fallback ---

    def _heuristic_copilot(self, history: List[Dict[str, Any]]) -> str:
        if not history:
            return "¡Hola! ¿En qué proyecto modular o industrial te podemos asesorar hoy?"
        last_msg = history[-1]["content"].lower()
        if "precio" in last_msg or "costo" in last_msg or "cotiz" in last_msg:
            return "¡Hola! Como cada una de nuestras estructuras (Flex Home, Cápsula Linvig, Cuartos Fríos o Bodegas) se personaliza a la medida de tu terreno y ubicación, los precios exactos se calculan en una breve sesión técnica de 10 minutos. ¿Te agendamos una llamada?"
        elif "agenda" in last_msg or "cita" in last_msg:
            return "Con gusto agendamos la llamada. Por favor dime qué día de la semana te queda mejor."
        return "Hola, con mucho gusto te ayudamos con tu consulta sobre ANCLA Special Projects. ¿Me darías más detalles?"

    def _heuristic_autopilot(self, contact: Any, last_message: str) -> str:
        name = (contact.first_name if (contact and hasattr(contact, 'first_name')) else str(contact)) or "cliente"
        notes = (contact.qualification_notes if (contact and hasattr(contact, 'qualification_notes')) else "") or ""
        lot_st = (contact.lot_status if (contact and hasattr(contact, 'lot_status')) else None) or ""
        lot_ct = (contact.lot_city if (contact and hasattr(contact, 'lot_city')) else None) or ""
        msg = last_message.lower()
        
        greeting = f"¡Hola {name}! 🏠✨ "

        # Pregunta / Confirmación sobre Lote Propio (Igual a Meta Ads)
        if lot_st == "Lote Propio":
            city_str = f" en {lot_ct}" if lot_ct else ""
            lot_callout = f"📍 *¡Excelente que ya cuentes con terreno propio{city_str}!* Esto facilita la preparación de cimentación y entrega en pocas semanas.\n\n"
        elif lot_st == "Buscando Lote":
            lot_callout = f"🏞️ *No te preocupes si aún estás buscando terreno*: nuestras estructuras modulares son adaptables a cualquier topografía una vez elijas tu lote.\n\n"
        else:
            lot_callout = f"🌱 *Para orientarte mejor*: ¿Cuentas actualmente con terreno / lote propio o estás en búsqueda?\n\n"

        opts_text = (
            f"{lot_callout}"
            "Cuéntame, **¿qué inquietudes tienes o cuál de nuestros modelos te llama más la atención para tu proyecto?** 💬✨\n\n"
            "Podemos resolver todas tus dudas directamente por este medio, o si en cualquier momento prefieres una atención guiada, podemos coordinar una **Visita Presencial en nuestro Showroom de Armenia** o una **Asesoría Virtual / Llamada Comercial**."
        )

        if "precio" in msg or "cuesta" in msg or "valor" in msg or "cotiz" in msg:
            return f"{greeting}Como nuestras soluciones modulares (**Flex Home** y **Cápsula Living**) se configuran a la medida de tu proyecto y terreno, los precios exactos y planos te los presentamos detalladamente en tu sesión. {opts_text}"
            
        elif "baño" in msg or "baño completo" in msg or "ducha" in msg or "inodoro" in msg:
            return f"{greeting}Sí, nuestras casas modulares vienen equipadas con baño 100% completo: incluye lavamanos con mueble, espejo, ducha con mampara en vidrio templado e inodoro de alta calidad.\n\n{opts_text}"

        elif "aislamiento" in msg or "aislante" in msg or "frío" in msg or "frio" in msg or "ruido" in msg or "acústico" in msg:
            return f"{greeting}Nuestros muros utilizan paneles tipo sándwich con lámina de acero galvanizado y aislamiento termoacústico con lana de roca. Esto asegura un confort térmico y acústico superior en cualquier clima.\n\n{opts_text}"

        elif "habitación" in msg or "habitaciones" in msg or "cuartos" in msg:
            return f"{greeting}La **Flex Home** cuenta con 2 habitaciones amplias y excelente distribución interior, mientras que la **Cápsula Living** es un módulo tipo suite ideal para suite de descanso o glamping.\n\n{opts_text}"

        elif "cocina" in msg or "cocineta" in msg:
            return f"{greeting}La cocina viene 100% instalada: incluye muebles superiores e inferiores, mesón de trabajo, lavaplatos en acero inoxidable y grifería de lujo.\n\n{opts_text}"

        elif "dimensión" in msg or "dimensiones" in msg or "medida" in msg or "tamaño" in msg:
            if "cápsula" in msg or "capsula" in msg or "linvig" in msg or "living" in msg:
                return f"{greeting}La **Cápsula Living** tiene un área habitacional de 28m² (tipo suite moderna de alta gama).\n\n{opts_text}"
            return f"{greeting}La **Flex Home** está disponible en versiones expandibles de 36m², 56m² y 72m² con distribución de 2 habitaciones, sala, comedor y cocina.\n\n{opts_text}"

        elif "plano" in msg or "planos" in msg:
            return f"{greeting}Contamos con los planos arquitectónicos detallados y distribuciones en 3D. {opts_text}"

        # Duda general / Solicitud de información de casas modulares
        return (
            f"{greeting}Con mucho gusto te compartimos información sobre nuestras casas modulares exhibidas. "
            f"Contamos con la línea **Flex Home** (modelos de 36m², 56m² y 72m² con 2 habitaciones, sala, comedor y cocina) "
            f"y la **Cápsula Living** (suite moderna de alta gama ideal para hospedaje o residencia).\n\n"
            f"Todas nuestras unidades están fabricadas con estructura en acero galvanizado, aislamiento termoacústico y acabados de lujo ready-to-move.\n\n"
            f"{opts_text}"
        )

    def _heuristic_ad_copy(self, product_description: str, tone: str) -> Dict[str, Any]:
        return {
            "headline": "¡Optimiza tus ventas con la IA de Google! 🚀",
            "body": f"Automatiza tus canales con '{product_description}'. CRM omnicanal y piloto automático 24/7.",
            "cta": "Más Información"
        }

ai_engine = AIEngine()
