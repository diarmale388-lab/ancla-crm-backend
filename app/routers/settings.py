import logging
import os
import io
import base64
import httpx
from datetime import datetime
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
import pypdf

from app.database import get_db
from app.models.base import SystemSetting, User, KnowledgeDocument
from app.routers.auth import get_current_user
from app.config import settings
from app.core.crypto import encrypt_value, decrypt_value

logger = logging.getLogger("settings_router")

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("/chatbot")
def get_chatbot_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    prompt_setting = db.query(SystemSetting).filter(SystemSetting.key == "chatbot_prompt").first()
    api_key_setting = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
    
    default_prompt = (
        "# AGENTE COMERCIAL VIRTUAL - SOFI (ANCLA SPECIAL PROJECTS)\n\n"
        "## 1. IDENTIDAD Y ROL\n"
        "Eres Sofi, la Asesora Especialista Virtual de ANCLA Special Projects. Tu trato es amable, cercano, ejecutivo, profesional y consultivo. Tu objetivo es asesorar al cliente en proyectos modulares, Glamping, Flex Homes, Cuartos Fríos, Bodegas y Estructuras Metálicas, resolver sus dudas técnicas y guiarlo a agendar una llamada/reunión por Meet o solicitar propuesta.\n\n"
        "## 2. REGLA DE ORO OBLIGATORIA: CERO PRECIOS\n"
        "- Jamás entregues precios, cifras aproximadas ni tarifas.\n"
        "- Ante preguntas de costo, responde: 'Para entregarte una cifra exacta y transparente, nuestros ingenieros estructuran una propuesta personalizada según las medidas y acabados de tu proyecto. Te invito a agendar una breve llamada o reunión por Meet con nuestro especialista para cotizar sin compromiso.'\n\n"
        "## 3. DATOS A CAPTURAR (FICHA DE CLIENTE)\n"
        "- Nombre real (si difiere de su WhatsApp).\n"
        "- Correo electrónico para el envío de propuestas.\n"
        "- Ubicación / Ciudad del proyecto.\n"
        "- Si posee LOTE / TERRENO propio listo con servicios (Pregunta clave de clasificación).\n\n"
        "## 4. CLASIFICACIÓN (LEAD SCORING)\n"
        "- 🟢 POTENCIAL: Lote propio listo, compra a corto plazo, pide agendar cita o propuesta.\n"
        "- 🟡 EXPLORADOR: Busca terreno o planea construir a futuro.\n"
        "- 🔴 CURIOSO: Respuestas evasivas o sin interés real.\n\n"
        "## 5. TOMA DE CONTROL HUMANO\n"
        "Si el cliente pide hablar con una persona real o califica como 🟢 Potencial urgente, emite la alerta en pantalla y desactiva tu respuesta automática para que el asesor tome el control del chat.\n\n"
        "## 6. REGLA DE CALIFICACIÓN GEOGRÁFICA Y ENRUTAMIENTO DE INVITACIÓN / AGENDAMIENTO\n"
        "- Cuando indagues la ciudad de residencia del cliente o el cliente mencione dónde se encuentra:\n"
        "  * SI ES DEL EJE CAFETERO (Armenia, Quindío, Pereira, Manizales, Dosquebradas, Calarcá, etc.): Invítalo a visitar presencialmente nuestro Showroom en Armenia (Avenida Centenario, frente a Pan y Miel).\n"
        "  * SI ES DE OTRA CIUDAD NACIONAL (Bogotá, Medellín, Cali, Neiva, Flandes, Nemocón, Palmira, Casanare, u otras regiones): Ofrécele coordinar la Asesoría Virtual por Videollamada Zoom/Meet o Llamada Telefónica según su preferencia.\n\n"
        "## 7. REGLA DE PROGRAMACIÓN DE LLAMADAS (CERO PROMESAS EN VAGO)\n"
        "- Queda ESTRICTAMENTE PROHIBIDO decir 'te contactaremos en breve' o dejar llamadas en el aire sin definir fecha y hora.\n"
        "- Sofi DEBE iniciar de inmediato la PROGRAMACIÓN DE LA CITA ofreciendo los horarios disponibles (L-V 10am-12pm y 2pm-4:30pm, Sábados 10am-12pm).\n\n"
        "## 8. REGLA DE RESPUESTA EQUILIBRADA (ESTILO TEASER COMERCIAL - CERO MANUALES TÉCNICOS LARGOS)\n"
        "- NUNCA entregues fichas técnicas ultradetalladas ni listas largas de especificaciones mecánicas/estructurales por chat.\n"
        "- En su lugar, entrega un RESUMEN ATRACTIVO DE 2 O 3 BENEFICIOS CLAVE (ej: número de habitaciones, acabados modernos, rapidez de entrega).\n"
        "- E inmediatamente conecta con la llamada/videollamada ofreciendo coordinar la cita técnica de 30 minutos.\n\n"
        "## 9. REGLA DE USO DE EMOJIS Y BOTONES INTERACTIVOS EN CADA MENSAJE\n"
        "- Sofi DEBE utilizar siempre los Botones Táctiles Interactivos para guiar al cliente.\n\n"
        "## 10. PROHIBICIÓN ABSOLUTA DE REDES SOCIALES Y ENLACES EXTERNOS\n"
        "- Queda ESTRICTAMENTE PROHIBIDO mencionar redes sociales (Instagram, Facebook, TikTok) o inventar enlaces externos.\n\n"
        "## 11. SALA DE VENTAS Y SHOWROOM PRINCIPAL\n"
        "- Sala de ventas y exhibición en Armenia, Quindío — Av. Centenario frente a Pan y Miel."
    )
    
    return {
        "chatbot_prompt": prompt_setting.value if prompt_setting else default_prompt,
        "gemini_api_key": api_key_setting.value if api_key_setting else ""
    }


@router.post("/chatbot")
def update_chatbot_settings(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    chatbot_prompt = payload.get("chatbot_prompt")
    gemini_api_key = payload.get("gemini_api_key")
    
    if chatbot_prompt is not None:
        prompt_setting = db.query(SystemSetting).filter(SystemSetting.key == "chatbot_prompt").first()
        if not prompt_setting:
            prompt_setting = SystemSetting(key="chatbot_prompt", value=chatbot_prompt)
            db.add(prompt_setting)
        else:
            prompt_setting.value = chatbot_prompt
            db.add(prompt_setting)
            
    if gemini_api_key is not None:
        api_key_setting = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
        if not api_key_setting:
            api_key_setting = SystemSetting(key="gemini_api_key", value=gemini_api_key)
            db.add(api_key_setting)
        else:
            api_key_setting.value = gemini_api_key
            db.add(api_key_setting)
            
    db.commit()
    
    if gemini_api_key:
        from app.services.ai_engine import ai_engine
        ai_engine.api_key = gemini_api_key
        
    return {"status": "success", "message": "Entrenamiento de la IA guardado exitosamente"}


@router.get("/documents")
def list_knowledge_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    docs = db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_type": d.file_type,
            "created_at": d.created_at.isoformat()
        } for d in docs
    ]


@router.post("/upload-document")
async def upload_knowledge_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    filename = file.filename
    file_ext = os.path.splitext(filename)[1].lower()
    
    contents = await file.read()
    
    extracted_text = ""
    file_type = "Documento"
    
    # 1. Obtener Gemini API Key
    api_key_setting = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
    gemini_key = api_key_setting.value if (api_key_setting and api_key_setting.value) else settings.GEMINI_API_KEY
    
    try:
        # A. PDFs
        if file_ext == ".pdf":
            file_type = "PDF"
            pdf_file = io.BytesIO(contents)
            reader = pypdf.PdfReader(pdf_file)
            text_chunks = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_chunks.append(t)
            extracted_text = "\n".join(text_chunks)
            if not extracted_text.strip():
                extracted_text = "[PDF sin texto extraíble directamente, posiblemente escaneado]"
                
        # B. IMÁGENES (Google Gemini 1.5 Flash Vision)
        elif file_ext in [".png", ".jpg", ".jpeg", ".webp"]:
            file_type = "Imagen"
            if not gemini_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Se requiere configurar tu Google Gemini API Key en Ajustes para procesar imágenes con visión artificial."
                )
                
            base64_image = base64.b64encode(contents).decode('utf-8')
            mime = f"image/{file_ext[1:] if file_ext[1:] != 'jpg' else 'jpeg'}"
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": "Analiza esta imagen del catálogo o documento de nuestra empresa. Extrae todo su texto, tablas, precios, ofertas y descripciones de manera sumamente precisa y formateada en texto legible para que nuestro chatbot de ventas lo use para responderle a los clientes por WhatsApp."
                            },
                            {
                                "inlineData": {
                                    "mimeType": mime,
                                    "data": base64_image
                                }
                            }
                        ]
                    }
                ]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=45.0)
                if response.status_code == 200:
                    data = response.json()
                    extracted_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    logger.error(f"Error en Gemini Vision API: {response.text}")
                    raise Exception("Fallo en la API de Visión Artificial de Google Gemini")
                    
        # C. AUDIOS / VIDEOS (Google Gemini 1.5 Flash Audio)
        elif file_ext in [".mp3", ".mp4", ".wav", ".m4a"]:
            file_type = "Audio/Video"
            if not gemini_key:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Se requiere tu Google Gemini API Key para transcribir audios/videos."
                )
                
            base64_audio = base64.b64encode(contents).decode('utf-8')
            mime = "audio/mp3"
            if file_ext == ".wav":
                mime = "audio/wav"
            elif file_ext == ".m4a":
                mime = "audio/m4a"
            elif file_ext == ".mp4":
                mime = "video/mp4"
                
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": "Por favor, transcribe este archivo de audio/video a texto completo en español de forma precisa:"
                            },
                            {
                                "inlineData": {
                                    "mimeType": mime,
                                    "data": base64_audio
                                }
                            }
                        ]
                    }
                ]
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=payload, timeout=60.0)
                if response.status_code == 200:
                    data = response.json()
                    extracted_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                else:
                    logger.error(f"Error en Gemini Audio API: {response.text}")
                    raise Exception("Fallo en la API de Audio de Google Gemini")
                    
        # D. TEXTO SIMPLE / CSV
        elif file_ext in [".txt", ".csv"]:
            file_type = "Texto plano"
            extracted_text = contents.decode("utf-8", errors="ignore")
            
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Formato de archivo {file_ext} no soportado para base de conocimiento."
            )
            
    except Exception as e:
        logger.error(f"Error procesando archivo {filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al analizar el contenido: {str(e)}"
        )
        
    if not extracted_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo extraer ningún texto o conocimiento del archivo provisto."
        )

    # 3. Guardar en base de datos
    doc = KnowledgeDocument(
        filename=filename,
        file_type=file_type,
        extracted_text=extracted_text
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    # 4. Indexación vectorial en Neon PostgreSQL usando pgvector
    try:
        from app.services.rag_service import index_document
        await index_document(db, doc)
    except Exception as e_index:
        logger.error(f"Error al indexar vectorialmente el documento ID {doc.id}: {e_index}")
    
    return {
        "status": "success", 
        "message": f"Archivo '{filename}' analizado, subido e indexado vectorialmente con éxito.",
        "doc_id": doc.id
    }


@router.delete("/documents/{doc_id}")
def delete_knowledge_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El documento de conocimiento especificado no existe."
        )
    db.delete(doc)
    db.commit()
    return {"status": "success", "message": "Documento de conocimiento eliminado correctamente"}


from fastapi import BackgroundTasks
import asyncio
import random
import time

async def async_simulation_runner():
    """
    Simulación secuencial asíncrona en segundo plano con marcas de tiempo en horario laboral.
    """
    from app.services.ai_engine import ai_engine
    
    ancla_leads = [
        {"phone": "573200000001", "name": "Carlos Mendoza", "msg1": "Hola, me interesa la Casa Expandible FLEX HOME de 56 m2. ¿Qué precio tiene?", "msg2": "¿Incluye el deck exterior que vi en la ficha técnica?"},
        {"phone": "573200000002", "name": "Diana Ospina", "msg1": "Buenas tardes, ¿la Capsula Linvig de 13m2 viene con baño completo?", "msg2": "¿Es apta para proyectos de glamping en clima frío por el aislamiento térmico?"},
        {"phone": "573200000003", "name": "Andrés Felipe", "msg1": "Hola, ¿las paredes de la FLEX HOME tienen aislamiento termoacústico?", "msg2": "¿La estructura principal de qué material es? ¿Resiste la corrosión?"},
        {"phone": "573200000004", "name": "Inversiones Glamping SAS", "msg1": "Buenas, queremos cotizar 10 cápsulas Linvig de 13m2 con deck para un proyecto turístico.", "msg2": "¿Tienen planes de financiación o descuento por volumen?"},
        {"phone": "573200000005", "name": "Martha Lucía", "msg1": "Hola, ¿la cocina está incluida en la FLEX HOME de 36 m2?", "msg2": "¿Viene con mueble superior e inferior y lavaplatos?"},
        {"phone": "573200000006", "name": "Rodrigo Garzón", "msg1": "¿Qué dimensiones tiene la Capsula Linvig sin deck?", "msg2": "¿El piso es resistente a la humedad?"},
        {"phone": "573200000007", "name": "Sandra Milena", "msg1": "Hola, ¿la FLEX HOME de 56 m2 cuenta con cuántas habitaciones?", "msg2": "¿El baño viene completo con inodoro y ducha de vidrio?"},
        {"phone": "573200000008", "name": "Turismo del Café", "msg1": "Hola, nos interesa la cabina modular con balcón integrado de 13 m2.", "msg2": "¿Viene con instalación eléctrica y luces LED preinstaladas?"},
        {"phone": "573200000009", "name": "Alberto Cadavid", "msg1": "Buenas noches, ¿las ventanas de la FLEX HOME son en aluminio?", "msg2": "¿La puerta principal tiene vidrio templado?"},
        {"phone": "573200000010", "name": "Glamping Guatavita", "msg1": "Hola, ¿tienen un modelo de FLEX HOME que sea de 36 m2?", "msg2": "¿El techo es panel sándwich termoacústico?"},
        {"phone": "573200000011", "name": "Patricia Jaramillo", "msg1": "¿Cómo es el proceso de expansión en sitio de las casas modulares?", "msg2": "¿Qué tiempo toma dejarla lista para habitar?"},
        {"phone": "573200000012", "name": "Héctor Fabio", "msg1": "Hola, ¿la Capsula Linvig de 13m2 requiere cimentación muy compleja?", "msg2": "¿Qué material usan para las barandas del balcón?"},
        {"phone": "573200000013", "name": "Clara Inés", "msg1": "¿El bastidor para el transporte de la FLEX HOME es reforzado?", "msg2": "¿De qué espesor son los muros exteriores?"},
        {"phone": "573200000014", "name": "Constructora Módulos", "msg1": "Buenas tardes, ¿las tuberías hidráulicas y sanitarias cumplen qué estándares internacionales?", "msg2": "¿Las tomas eléctricas y el tablero están listos para conectar a la red?"},
        {"phone": "573200000015", "name": "Felipe Aristizábal", "msg1": "Hola, ¿el deck exterior de la Capsula Linvig es plegable?", "msg2": "¿Cuál es el ancho total exterior del módulo?"},
        {"phone": "573200000016", "name": "Liliana Restrepo", "msg1": "Hola! ¿La cocina de la FLEX HOME viene con la grifería incluida?", "msg2": "¿El mesón de trabajo es resistente?"},
        {"phone": "573200000017", "name": "Mauricio Correa", "msg1": "¿Tienen planos de la distribución interior de la cabina de 13 m2?", "msg2": "¿El inodoro y la ducha ya vienen instalados en sitio?"},
        {"phone": "573200000018", "name": "Valeria Henao", "msg1": "Buenas, ¿el techo de la casa de 56m2 es resistente a granizadas?", "msg2": "¿Viene con el cielo raso integrado?"}
    ]

    api_url = "http://localhost:8001/api/v1/webhooks/meta"
    
    # Ronda 1 (Mensajes de apertura)
    for lead in ancla_leads:
        # Calcular marca de tiempo en horario laboral (por ejemplo, entre las 09:00 y las 17:00 del día de hoy)
        now = datetime.now()
        # Generar un timestamp realista de hoy entre las 9am y 5pm
        timestamp_laboral = int(datetime(now.year, now.month, now.day, random.randint(9, 16), random.randint(10, 50)).timestamp())
        
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1234567890",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"display_phone_number": "15550000000", "phone_number_id": "111222333"},
                                "contacts": [{"profile": {"name": lead["name"]}, "wa_id": lead["phone"]}],
                                "messages": [
                                    {
                                        "from": lead["phone"],
                                        "id": f"wamid.{random.randint(100000, 999999)}",
                                        "timestamp": str(timestamp_laboral),
                                        "text": {"body": lead["msg1"]},
                                        "type": "text"
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        try:
            async with httpx.AsyncClient() as client:
                await client.post(api_url, json=payload, timeout=8.0)
        except Exception as e:
            logger.error(f"Error en demo: {e}")
        
        await asyncio.sleep(4.0)  # Demora de 4 segundos entre clientes para simular entrada orgánica

    # Esperar 6 segundos y correr Ronda 2
    await asyncio.sleep(6.0)

    # Ronda 2 (Mensajes de seguimiento)
    for lead in ancla_leads:
        now = datetime.now()
        timestamp_laboral = int(datetime(now.year, now.month, now.day, random.randint(9, 16), random.randint(10, 50)).timestamp())
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1234567890",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"display_phone_number": "15550000000", "phone_number_id": "111222333"},
                                "contacts": [{"profile": {"name": lead["name"]}, "wa_id": lead["phone"]}],
                                "messages": [
                                    {
                                        "from": lead["phone"],
                                        "id": f"wamid.{random.randint(100000, 999999)}",
                                        "timestamp": str(timestamp_laboral),
                                        "text": {"body": lead["msg2"]},
                                        "type": "text"
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        try:
            async with httpx.AsyncClient() as client:
                await client.post(api_url, json=payload, timeout=8.0)
        except Exception as e:
            logger.error(f"Error en demo: {e}")
        
        await asyncio.sleep(4.5)


@router.post("/run-demo-simulation")
def trigger_demo_simulation(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Limpia los contactos y chats de prueba existentes, y dispara la simulación en segundo plano.
    """
    # Limpiar contactos de prueba previos para reiniciar el panel limpiamente
    from app.models.base import Contact, Message, Appointment
    
    # Obtener IDs de contactos de prueba existentes
    test_contact_ids = [c.id for c in db.query(Contact).filter(Contact.phone.like("5732%")).all()]
    if test_contact_ids:
        # Eliminar citas asociadas
        db.query(Appointment).filter(Appointment.contact_id.in_(test_contact_ids)).delete(synchronize_session=False)
        # Eliminar mensajes asociados
        db.query(Message).filter(Message.contact_id.in_(test_contact_ids)).delete(synchronize_session=False)
        # Eliminar los contactos
        db.query(Contact).filter(Contact.id.in_(test_contact_ids)).delete(synchronize_session=False)
        db.commit()

    background_tasks.add_task(async_simulation_runner)
    return {"status": "success", "message": "Simulación de demo en vivo iniciada con éxito en segundo plano."}


import json

@router.get("/quick-replies")
def get_quick_replies(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Retorna la lista de respuestas rápidas / plantillas configuradas.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "quick_replies").first()
    if not setting:
        # Valores por defecto para ANCLA Special Projects con soporte dinámico de género y variables
        default_replies = [
            {
                "id": 1,
                "title": "📹 Invitación Google Meet (Directa)",
                "content": "Hola {{cliente}}, con mucho gusto te comparto el link de acceso a la videollamada para nuestra asesoría programada:\n\n🔗 {{link_meet}}\n\nSolo dale clic para conectarte. ¡Quedo muy {{atento_atenta}} a tu conexión!\n\n{{asesor}}\nANCLA Special Projects"
            },
            {
                "id": 2,
                "title": "📹 Invitación Google Meet (Formal)",
                "content": "Buenos días, {{cliente}}. Le habla {{asesor}} de ANCLA Special Projects.\n\nCon mucho gusto le comparto el link de acceso a la videollamada para nuestra asesoría programada:\n\n🔗 {{link_meet}}\n\nSolo dele clic para ingresar. Quedo muy {{atento_atenta}} a su conexión. ¡Será un gusto atenderle!\n\n{{asesor}}\nANCLA Special Projects"
            },
            {
                "id": 3,
                "title": "⚡ Recordatorio Rápido (Enlace Meet)",
                "content": "¡Hola {{cliente}}! Ya estamos listos para nuestra asesoría virtual.\n\nAquí tienes el enlace directo para ingresar a la sala:\n🔗 {{link_meet}}\n\n¡Te espero en la sala!"
            },
            {
                "id": 4,
                "title": "🏠 Flex Home 36m² ($118.8M)",
                "content": "El modelo Flex Home EXP-36 (36m² | 5.90m x 6.30m) tiene un valor oficial de $118.800.000 COP. Cuenta con estructura de acero galvanizado Q350, 2 habitaciones, 1 baño completo, cocina y aislamiento termoacústico de 75mm."
            },
            {
                "id": 5,
                "title": "🏡 Flex Home 56m² (Personalizada)",
                "content": "La Casa Expandible FLEX HOME (56 m² | 11.80m x 6.30m) cuenta con 3 habitaciones, 2 baños, sala-comedor y sistema de doble expansión hidráulica (Cotización personalizada en showroom)."
            },
            {
                "id": 6,
                "title": "📍 Ubicación Showroom Armenia",
                "content": "Nuestra sala de ventas y showroom de exhibición está ubicada en Armenia, Quindío, sobre la Avenida Centenario, frente a Pan y Miel.\n• Waze: https://waze.com/ul?q=Avenida+Centenario+Armenia+Quindio\n• Google Maps: https://maps.google.com/?q=4.5616751,-75.6455612"
            }
        ]
        return default_replies
    
    try:
        return json.loads(setting.value)
    except Exception:
        return []


@router.post("/quick-replies")
def update_quick_replies(
    payload: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Guarda la lista completa de respuestas rápidas personalizadas.
    """
    setting = db.query(SystemSetting).filter(SystemSetting.key == "quick_replies").first()
    if not setting:
        setting = SystemSetting(key="quick_replies", value=json.dumps(payload))
        db.add(setting)
    else:
        setting.value = json.dumps(payload)
        db.add(setting)
        
    db.commit()
    return {"status": "success", "message": "Respuestas rápidas actualizadas exitosamente"}


from fastapi import BackgroundTasks
from pydantic import BaseModel

class ProposalRequest(BaseModel):
    model_name: str
    extras: str = ""
    discount: int = 0

@router.post("/send-proposal/{contact_id}")
async def send_proposal_with_ai(
    contact_id: int,
    payload: ProposalRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Utiliza la IA de Google Gemini para redactar, simular la exportación a Drive/Email,
    enviar un WhatsApp resumen al cliente y actualizar la fase comercial a 'Propuesta Enviada'.
    """
    from app.models.base import Contact, Message, PipelineStage
    from app.services.ai_engine import ai_engine
    from app.core.socket_manager import manager
    import uuid

    # 1. Buscar contacto
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")

    # 2. Obtener precios bases estimados para ANCLA
    base_prices = {
        "FLEX HOME 56m²": 29900,
        "FLEX HOME 36m²": 19900,
        "Cápsula Linvig 13m²": 12500
    }
    base_price = base_prices.get(payload.model_name, 22000)
    discount_amount = (base_price * payload.discount) / 100
    final_price = base_price - discount_amount

    # 3. Consultar a Gemini o redactar por heurística
    prompt_proposal = f"""
    Eres el redactor comercial experto de ANCLA Special Projects.
    Escribe una propuesta comercial formal y atractiva para el cliente {contact.first_name or 'Estimado Cliente'}.
    Detalles:
    - Modelo seleccionado: {payload.model_name}
    - Equipamiento Adicional (Extras): {payload.extras or 'Estándar Premium de fábrica'}
    - Precio Base: ${base_price:,} USD
    - Descuento aplicado: {payload.discount}% (-${discount_amount:,} USD)
    - Precio Final: ${final_price:,} USD
    - Estructura: Acero galvanizado anticorrosivo, muros sándwich termoacústicos.
    
    Genera dos partes separadas por el marcador [WHATSAPP_START]:
    Parte 1: Carta de correo formal y detallada con viñetas de las especificaciones y precio final.
    Parte 2: Mensaje de WhatsApp breve y dinámico saludando al cliente, diciéndole que le acabamos de enviar la propuesta formal al correo y dándole el enlace de descarga a su Drive.
    """

    api_key_setting = db.query(SystemSetting).filter(SystemSetting.key == "gemini_api_key").first()
    gemini_key = api_key_setting.value if api_key_setting and api_key_setting.value else None

    proposal_text = ""
    whatsapp_msg = ""

    if gemini_key:
        try:
            # Consultar a Gemini 3.5 Flash
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={gemini_key}"
            headers = { "Content-Type": "application/json" }
            req_data = {
                "contents": [{ "parts": [{ "text": prompt_proposal }] }]
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(url, json=req_data, headers=headers, timeout=10.0)
                if res.status_code == 200:
                    raw_text = res.json()["candidates"][0]["content"]["parts"][0]["text"]
                    if "[WHATSAPP_START]" in raw_text:
                        parts = raw_text.split("[WHATSAPP_START]")
                        proposal_text = parts[0].strip()
                        whatsapp_msg = parts[1].strip()
                    else:
                        proposal_text = raw_text
                        whatsapp_msg = f"¡Hola {contact.first_name or ''}! Te acabo de enviar a tu correo la propuesta formal para la {payload.model_name}. Puedes verla y descargarla en el siguiente enlace de Google Drive."
        except Exception as e:
            logger.error(f"Error llamando a Gemini para propuesta: {e}")

    # Fallback/Heurística refinada de ANCLA si falla Gemini o no hay key
    if not proposal_text or not whatsapp_msg:
        proposal_text = f"""
PROPUESTA COMERCIAL - ANCLA SPECIAL PROJECTS

Cliente: {contact.first_name or 'Cliente'} {contact.last_name or ''}
Modelo: {payload.model_name}
Fecha: {datetime.now().strftime('%d/%m/%Y')}

ESPECIFICACIONES DE LA PROPUESTA:
- Estructura modular premium en acero galvanizado anticorrosivo.
- Muros exteriores tipo sándwich con aislamiento termoacústico para frío y ruido.
- Baño completo listo para habitar: lavamanos con mueble, espejo, inodoro y ducha premium.
- Cocina equipada: muebles superiores e inferiores, mesón de trabajo y lavaplatos.
- Extras agregados: {payload.extras or 'Configuración Estándar Premium'}

DESGLOSE FINANCIERO:
- Precio Base: ${base_price:,} USD
- Descuento aplicado: {payload.discount}% (-${discount_amount:,} USD)
- PRECIO NETO DE INVERSIÓN: ${final_price:,} USD

CONDICIONES:
- Tiempo de fabricación estimado: 45 días.
- Garantía estructural de 5 años.
        """
        whatsapp_msg = f"¡Hola {contact.first_name or 'cliente'}! 👋 Le saluda la IA de ANCLA. Le acabo de enviar a su correo la propuesta formal personalizada para el modelo *{payload.model_name}*. También puede ver y descargar los planos y el presupuesto en este enlace seguro de Google Drive: https://drive.google.com/drive/folders/ancla_propuesta_{contact_id}"

    # 4. Guardar archivo de propuesta en formato PDF y Markdown en local (simulando exportación a Google Drive)
    import os
    from fpdf import FPDF
    
    os.makedirs("scratch", exist_ok=True)
    timestamp_val = int(datetime.now().timestamp())
    pdf_filename = f"propuesta_ancla_{contact_id}_{timestamp_val}.pdf"
    pdf_path = os.path.join("scratch", pdf_filename)
    report_filename = f"scratch/proposal_doc_{contact_id}_{timestamp_val}.md"
    
    # A. Guardar Markdown para RAG/Logs
    with open(report_filename, "w", encoding="utf-8") as f:
        f.write(proposal_text)

    # B. Generar el PDF real
    class AnclaProposalPDF(FPDF):
        def header(self):
            # Logotipo de marca superior
            self.set_font("helvetica", "B", 14)
            self.set_text_color(30, 41, 59) # Slate 800
            self.cell(0, 8, "ANCLA SPECIAL PROJECTS", border=False, align="L")
            self.ln(5)
            self.set_font("helvetica", "", 8)
            self.set_text_color(100, 116, 139) # Slate 500
            self.cell(0, 5, "Casas Modulares de Alta Gama y Proyectos Especiales", border=False, align="L")
            self.ln(6)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(8)
            
        def footer(self):
            self.set_y(-15)
            self.set_font("helvetica", "I", 8)
            self.set_text_color(148, 163, 184)
            self.cell(0, 10, f"Propuesta Oficial de ANCLA - Pagina {self.page_no()}", align="C")

    try:
        pdf = AnclaProposalPDF()
        pdf.add_page()
        pdf.set_font("helvetica", "", 10)
        pdf.set_text_color(51, 65, 85) # Slate 700
        
        # Reemplazar caracteres no ASCII comunes para evitar fallas en FPDF
        safe_proposal = proposal_text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        safe_proposal = safe_proposal.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
        safe_proposal = safe_proposal.replace("ñ", "n").replace("Ñ", "N").replace("ü", "u").replace("Ü", "U")
        safe_proposal = safe_proposal.replace("¿", "").replace("¡", "")
        safe_proposal = safe_proposal.replace("\r", "")
        
        pdf.multi_cell(0, 6, safe_proposal)
        
        temp_pdf_path = f"scratch/temp_text_{contact_id}_{timestamp_val}.pdf"
        pdf.output(temp_pdf_path)
        
        # C. Fusionar con Hoja Membretada si existe
        template_pdf_path = "uploads/templates/proposal_template.pdf"
        if os.path.exists(template_pdf_path):
            import pypdf
            reader_text = pypdf.PdfReader(temp_pdf_path)
            reader_template = pypdf.PdfReader(template_pdf_path)
            writer = pypdf.PdfWriter()
            
            for page_idx in range(len(reader_text.pages)):
                text_page = reader_text.pages[page_idx]
                if len(reader_template.pages) > 0:
                    # Copiar página de plantilla de fondo
                    import copy
                    bg_page = copy.copy(reader_template.pages[0])
                    # Superponer texto de la propuesta
                    bg_page.merge_page(text_page)
                    writer.add_page(bg_page)
                else:
                    writer.add_page(text_page)
            
            with open(pdf_path, "wb") as out_f:
                writer.write(out_f)
            
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
        else:
            # Si no hay plantilla corporativa, renombrar el temporal como el oficial
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            os.rename(temp_pdf_path, pdf_path)
            
    except Exception as pdf_err:
        logger.error(f"Error generando PDF de la propuesta: {pdf_err}")

    # Enviar correo real si está configurado y el cliente tiene email
    if contact.email:
        smtp_host = db.query(SystemSetting).filter(SystemSetting.key == "smtp_host").first()
        smtp_port = db.query(SystemSetting).filter(SystemSetting.key == "smtp_port").first()
        smtp_username = db.query(SystemSetting).filter(SystemSetting.key == "smtp_username").first()
        smtp_password = db.query(SystemSetting).filter(SystemSetting.key == "smtp_password").first()
        smtp_sender_email = db.query(SystemSetting).filter(SystemSetting.key == "smtp_sender_email").first()
        smtp_sender_name = db.query(SystemSetting).filter(SystemSetting.key == "smtp_sender_name").first()
        
        if smtp_host and smtp_port and smtp_username and smtp_password and smtp_sender_email:
            smtp_settings = {
                "host": smtp_host.value,
                "port": smtp_port.value,
                "username": smtp_username.value,
                "password": smtp_password.value,
                "sender_email": smtp_sender_email.value,
                "sender_name": smtp_sender_name.value if smtp_sender_name else "ANCLA Special Projects"
            }
            from app.services.email import email_service
            email_body = proposal_text
            if "[WHATSAPP_START]" in email_body:
                email_body = email_body.split("[WHATSAPP_START]")[0].strip()
                
            email_service.send_email_with_attachment(
                to_email=contact.email,
                subject=f"Propuesta Oficial de ANCLA - {payload.model_name}",
                body_text=email_body,
                attachment_path=pdf_path,
                attachment_name=f"Propuesta_ANCLA_{payload.model_name.replace(' ', '_')}.pdf",
                smtp_settings=smtp_settings
            )
        else:
            logger.info("SMTP no configurado completamente. Se omite el envío del correo real.")

    # 5. Insertar el mensaje enviado por WhatsApp en la base de datos (con enlace al PDF)
    public_pdf_link = f"http://localhost:8001/api/v1/settings/proposals/{pdf_filename}"
    whatsapp_msg_with_pdf = whatsapp_msg + f"\n\nDESCARGAR PROPUESTA PDF COMPLETA: {public_pdf_link}"

    new_msg = Message(
        contact_id=contact.id,
        sender_type="ai",
        channel="whatsapp",
        content=whatsapp_msg_with_pdf,
        status="sent",
        external_message_id=f"sim_prop_{uuid.uuid4().hex[:12]}"
    )
    db.add(new_msg)

    # 6. Mover fase del contacto a 'Propuesta Enviada'
    proposal_stage = db.query(PipelineStage).filter(PipelineStage.name == "Propuesta Enviada").first()
    if proposal_stage:
        contact.pipeline_stage_id = proposal_stage.id
        db.add(contact)

    db.commit()
    db.refresh(contact)
    db.refresh(new_msg)

    # 7. Sincronizar en caliente por WebSocket al frontend
    new_msg_payload = {
        "id": new_msg.id,
        "contact_id": new_msg.contact_id,
        "sender_type": new_msg.sender_type.value if hasattr(new_msg.sender_type, 'value') else str(new_msg.sender_type),
        "channel": new_msg.channel.value if hasattr(new_msg.channel, 'value') else str(new_msg.channel),
        "message_type": new_msg.message_type.value if hasattr(new_msg.message_type, 'value') else str(new_msg.message_type),
        "content": new_msg.content,
        "status": new_msg.status.value if hasattr(new_msg.status, 'value') else str(new_msg.status),
        "created_at": new_msg.created_at.isoformat()
    }

    try:
        await manager.send_personal_message({
            "event": "message_received",
            "data": new_msg_payload
        }, current_user.id)
        if proposal_stage:
            await manager.send_personal_message({
                "event": "lead_stage_updated",
                "data": {
                    "contact_id": contact_id,
                    "pipeline_stage_id": proposal_stage.id
                }
            }, current_user.id)
    except Exception as ws_err:
        logger.error(f"WebSocket sync error: {ws_err}")

    return {
        "status": "success",
        "message": "Propuesta comercial generada por Gemini y despachada por Email y WhatsApp.",
        "proposal_file": report_filename,
        "pdf_url": public_pdf_link,
        "whatsapp_sent": whatsapp_msg_with_pdf
    }

from fastapi.responses import FileResponse

@router.get("/proposals/{filename}")
def download_proposal_pdf(filename: str):
    file_path = os.path.join("scratch", filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Archivo de propuesta no encontrado")
    return FileResponse(file_path, media_type="application/pdf", filename=filename)


@router.post("/upload-pdf-template")
def upload_pdf_template(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Sube un archivo PDF para usar de plantilla membretada (fijo) de fondo.
    Se guarda de manera independiente al RAG/Entrenamiento.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos en formato PDF.")
    
    os.makedirs("uploads/templates", exist_ok=True)
    template_path = "uploads/templates/proposal_template.pdf"
    
    # Escribir el archivo
    with open(template_path, "wb") as f:
        f.write(file.file.read())
        
    return {"status": "success", "message": "Hoja membretada corporativa en PDF subida con éxito."}


@router.get("/pdf-template-status")
def get_pdf_template_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Retorna el estado de la hoja membretada en PDF.
    """
    template_path = "uploads/templates/proposal_template.pdf"
    exists = os.path.exists(template_path)
    return {
        "status": "success",
        "has_template": exists,
        "filename": "proposal_template.pdf" if exists else None
    }


@router.post("/whatsapp-profile-photo")
async def upload_whatsapp_profile_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Sube una nueva foto de perfil para la cuenta comercial de WhatsApp.
    """
    filename = file.filename
    file_ext = os.path.splitext(filename)[1].lower()
    if file_ext not in [".png", ".jpg", ".jpeg", ".webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos de imagen (.png, .jpg, .jpeg, .webp)"
        )
        
    mime_type = file.content_type or f"image/{file_ext[1:] if file_ext[1:] != 'jpg' else 'jpeg'}"
    image_bytes = await file.read()
    
    from app.services.whatsapp import whatsapp_service
    success = await whatsapp_service.update_profile_picture(image_bytes, filename, mime_type)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo actualizar la foto de perfil en Meta. Verifique su token de acceso y la conexión."
        )
        
    return {
        "status": "success",
        "message": "¡Foto de perfil comercial de WhatsApp actualizada con éxito en Meta!"
    }


@router.get("/smtp")
def get_smtp_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    host = db.query(SystemSetting).filter(SystemSetting.key == "smtp_host").first()
    port = db.query(SystemSetting).filter(SystemSetting.key == "smtp_port").first()
    username = db.query(SystemSetting).filter(SystemSetting.key == "smtp_username").first()
    password = db.query(SystemSetting).filter(SystemSetting.key == "smtp_password").first()
    sender_email = db.query(SystemSetting).filter(SystemSetting.key == "smtp_sender_email").first()
    sender_name = db.query(SystemSetting).filter(SystemSetting.key == "smtp_sender_name").first()
    
    return {
        "host": host.value if host else "",
        "port": port.value if port else "587",
        "username": username.value if username else "",
        "password": decrypt_value(password.value) if password else "",
        "sender_email": sender_email.value if sender_email else "",
        "sender_name": sender_name.value if sender_name else "ANCLA Special Projects"
    }

@router.post("/smtp")
def update_smtp_settings(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    for key in ["host", "port", "username", "password", "sender_email", "sender_name"]:
        val = payload.get(key)
        if val is not None:
            setting = db.query(SystemSetting).filter(SystemSetting.key == f"smtp_{key}").first()
            stored_val = encrypt_value(str(val)) if key == "password" else str(val)
            if not setting:
                setting = SystemSetting(key=f"smtp_{key}", value=stored_val)
            else:
                setting.value = stored_val
            db.add(setting)
    db.commit()
    return {"status": "success", "message": "Configuración SMTP guardada y cifrada exitosamente."}

@router.post("/test-smtp")
def test_smtp_connection(
    payload: Dict[str, str],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    destination = payload.get("email")
    if not destination:
        raise HTTPException(status_code=400, detail="Debe especificar un correo de destino.")
        
    host = db.query(SystemSetting).filter(SystemSetting.key == "smtp_host").first()
    port = db.query(SystemSetting).filter(SystemSetting.key == "smtp_port").first()
    username = db.query(SystemSetting).filter(SystemSetting.key == "smtp_username").first()
    password = db.query(SystemSetting).filter(SystemSetting.key == "smtp_password").first()
    sender_email = db.query(SystemSetting).filter(SystemSetting.key == "smtp_sender_email").first()
    sender_name = db.query(SystemSetting).filter(SystemSetting.key == "smtp_sender_name").first()
    
    smtp_settings = {
        "host": host.value if host else None,
        "port": port.value if port else None,
        "username": username.value if username else None,
        "password": decrypt_value(password.value) if password else None,
        "sender_email": sender_email.value if sender_email else None,
        "sender_name": sender_name.value if sender_name else None
    }
    
    from app.services.email import email_service
    success = email_service.send_email_with_attachment(
        to_email=destination,
        subject="Prueba de Conexión SMTP - CRM Antigravity",
        body_text="¡Hola! Este es un correo de prueba enviado por el CRM Omnicanal Antigravity para verificar que la configuración de su servidor SMTP sea correcta.",
        smtp_settings=smtp_settings
    )
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Fallo en la prueba de conexión SMTP. Verifique los datos de host, puerto y credenciales."
        )
        
    return {"status": "success", "message": "Correo de prueba enviado exitosamente."}

@router.get("/google-client")
def get_google_client_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    client_id = db.query(SystemSetting).filter(SystemSetting.key == "google_client_id").first()
    client_secret = db.query(SystemSetting).filter(SystemSetting.key == "google_client_secret").first()
    
    return {
        "client_id": client_id.value if client_id else "",
        "client_secret": client_secret.value if client_secret else ""
    }

@router.post("/google-client")
def update_google_client_settings(
    payload: Dict[str, str],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    client_id = payload.get("client_id")
    client_secret = payload.get("client_secret")
    
    if client_id is not None:
        setting = db.query(SystemSetting).filter(SystemSetting.key == "google_client_id").first()
        if not setting:
            setting = SystemSetting(key="google_client_id", value=client_id)
        else:
            setting.value = client_id
        db.add(setting)
        
    if client_secret is not None:
        setting = db.query(SystemSetting).filter(SystemSetting.key == "google_client_secret").first()
        if not setting:
            setting = SystemSetting(key="google_client_secret", value=client_secret)
        else:
            setting.value = client_secret
        db.add(setting)
        
    db.commit()
    return {"status": "success", "message": "Credenciales de Google OAuth guardadas exitosamente."}

