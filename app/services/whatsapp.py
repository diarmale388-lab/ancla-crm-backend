import logging
import httpx
import asyncio
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger("whatsapp_service")

VERIFIED_META_TOKEN = "EAAjwLoRIerUBSHHdpgf31uI1joi6jaALZB7XuPxOQANI1FkgIzYRoZCvIzqETZAaFbxK8aUYHrrZA6HPW3rZAdhv2ZCPviLshlJa3mxJGN7IP4lhXzHAgYjtMHDqoJhrE5fZB4lBdamYO87hu41YYFRKQNSU1rR1ZBNvHneAZBJsD4WQRS3bqJe3t69wA0ZBsepgZDZD"
VERIFIED_PHONE_ID = "1309006675619043"

class WhatsAppService:
    def get_credentials(self, db: Optional[Any] = None):
        access_token = VERIFIED_META_TOKEN
        phone_id = VERIFIED_PHONE_ID

        if db:
            try:
                from app.models.base import SystemSetting
                tok = db.query(SystemSetting).filter(SystemSetting.key == "meta_access_token").first()
                if tok and tok.value and len(tok.value.strip()) > 30:
                    access_token = tok.value.strip()
                pid = db.query(SystemSetting).filter(SystemSetting.key == "whatsapp_phone_number_id").first()
                if pid and pid.value and len(pid.value.strip()) > 5:
                    phone_id = pid.value.strip()
            except Exception as e:
                logger.error(f"Error al leer credenciales Meta de la BD: {e}")

        return access_token, phone_id

    async def send_text_message(self, to_phone: str, message_text: str, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Envía un mensaje de texto libre por WhatsApp con lógica de reintento automático.
        """
        access_token, phone_id = self.get_credentials(db)
        if not access_token or not phone_id:
            logger.error("WhatsAppService no está configurado (falta token o ID de número).")
            return None

        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {
                "body": message_text
            }
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                    response_data = response.json()
                    if response.status_code == 200:
                        logger.info(f"Mensaje enviado con éxito por WhatsApp a {to_phone} (Intento {attempt+1})")
                        try:
                            from app.services.audit_logger import add_audit_log
                            msg_id = response_data.get("messages", [{}])[0].get("id", "N/A")
                            add_audit_log("success", "webhook", f"✅ Mensaje WhatsApp enviado a {to_phone}. Meta Message ID: {msg_id}")
                        except Exception:
                            pass
                        return response_data
                    
                    logger.warning(f"Intento {attempt+1} falló. Código Meta: {response.status_code}. Respuesta: {response_data}")
                    try:
                        from app.services.audit_logger import add_audit_log
                        err_detail = response_data.get("error", {}).get("message", str(response_data))
                        add_audit_log("error", "meta", f"❌ Fallo al enviar WhatsApp a {to_phone} (HTTP {response.status_code}): {err_detail}")
                    except Exception:
                        pass
                    
                    # Verificar si es un error transitorio
                    is_transient = False
                    if isinstance(response_data, dict) and "error" in response_data:
                        err = response_data["error"]
                        is_transient = err.get("is_transient", False) or err.get("code") in [2, 4, 17, 368]
                    
                    if not is_transient or attempt == max_retries - 1:
                        logger.error(f"Error no reintentable o sin intentos restantes en WhatsApp API: {response_data}")
                        return None
                    
                    await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Error de red en intento {attempt+1} al enviar WhatsApp: {e}")
                try:
                    from app.services.audit_logger import add_audit_log
                    add_audit_log("error", "meta", f"❌ Error de conexión al enviar WhatsApp a {to_phone}: {e}")
                except Exception:
                    pass
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(1.0)
        return None

    async def send_interactive_buttons(self, to_phone: str, body_text: str, buttons: list, header_text: Optional[str] = None, footer_text: Optional[str] = None, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Envía un mensaje interactivo con botones de respuesta rápida por WhatsApp Cloud API.
        buttons list format: [{"id": "btn_yes", "title": "Sí, confirmar"}, {"id": "btn_no", "title": "Cambiar hora"}]
        """
        access_token, phone_id = self.get_credentials(db)
        if not access_token or not phone_id:
            return None

        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Formatear el texto para que la conversación en el CRM muestre visualmente los botones enviados
        btn_lines = [f"  {idx+1}️⃣ {str(b['title']).strip()}" for idx, b in enumerate(buttons)]
        btn_footer = "\n\n🔘 [Botones Táctiles Enviados]:\n" + "\n".join(btn_lines)
        full_display_body = body_text + btn_footer if "🔘 [Botones Táctiles" not in body_text else body_text

        interactive_data = {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": b["id"],
                            "title": str(b["title"]).strip()[:20]
                        }
                    }
                    for b in buttons
                ]
            }
        }
        
        if header_text:
            interactive_data["header"] = {"type": "text", "text": header_text[:60]}
        if footer_text:
            interactive_data["footer"] = {"text": footer_text[:60]}
            
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "interactive",
            "interactive": interactive_data
        }
        
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, json=payload, timeout=10.0)
                if res.status_code == 200:
                    logger.info(f"Botones interactivos enviados con éxito a {to_phone}")
                    return res.json()
                else:
                    logger.warning(f"Fallo en botones interactivos Meta ({res.status_code}): {res.text}. Usando fallback a texto.")
                    return await self.send_text_message(to_phone, full_display_body, db)
        except Exception as e:
            logger.error(f"Excepción en envío de botones interactivos: {e}")
            return await self.send_text_message(to_phone, full_display_body, db)

    async def send_interactive_list(self, to_phone: str, header_text: str, body_text: str, button_text: str, sections: list, footer_text: Optional[str] = None, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Envía un menú desplegable (Interactive List) por WhatsApp Cloud API.
        """
        access_token, phone_id = self.get_credentials(db)
        if not access_token or not phone_id:
            return None

        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        # Formatear la lista para visualización clara en el chat del CRM
        list_lines = []
        for sec in sections:
            list_lines.append(f"📋 *{sec.get('title', 'Opciones')}*:")
            for row in sec.get("rows", []):
                desc_str = f" - {row.get('description')}" if row.get('description') else ""
                list_lines.append(f"  • {row.get('title')}{desc_str}")
        list_summary = "\n\n📱 [Menú Desplegable de Opciones Enviado]:\n" + "\n".join(list_lines)
        full_display_body = body_text + list_summary if "📱 [Menú Desplegable" not in body_text else body_text

        list_data = {
            "type": "list",
            "header": {"type": "text", "text": header_text[:60]},
            "body": {"text": body_text},
            "action": {
                "button": button_text[:20],
                "sections": sections
            }
        }
        if footer_text:
            list_data["footer"] = {"text": footer_text[:60]}
            
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "interactive",
            "interactive": list_data
        }
        
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, json=payload, timeout=10.0)
                if res.status_code == 200:
                    logger.info(f"Menú de lista interactiva enviado con éxito a {to_phone}")
                    return res.json()
                else:
                    logger.warning(f"Fallo en lista interactiva Meta ({res.status_code}): {res.text}. Usando fallback a texto.")
                    return await self.send_text_message(to_phone, full_display_body, db)
        except Exception as e:
            logger.error(f"Excepción en envío de lista interactiva: {e}")
            return await self.send_text_message(to_phone, full_display_body, db)

    async def send_template_message(self, to_phone: str, template_name: str, language_code: str = "es", components: list = None, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Envía un mensaje basado en una plantilla pre-aprobada con lógica de reintento automático.
        """
        access_token, phone_id = self.get_credentials(db)
        if not access_token or not phone_id:
            logger.error("WhatsAppService no está configurado.")
            return None

        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {
                    "code": language_code
                }
            }
        }
        
        if components:
            payload["template"]["components"] = components

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                    response_data = response.json()
                    if response.status_code == 200:
                        logger.info(f"Plantilla enviada con éxito por WhatsApp a {to_phone} (Intento {attempt+1})")
                        return response_data
                    
                    logger.warning(f"Intento {attempt+1} de plantilla falló. Respuesta: {response_data}")
                    
                    is_transient = False
                    if isinstance(response_data, dict) and "error" in response_data:
                        err = response_data["error"]
                        is_transient = err.get("is_transient", False) or err.get("code") in [2, 4, 17, 368]
                    
                    if not is_transient or attempt == max_retries - 1:
                        logger.error(f"Error no reintentable en plantilla: {response_data}")
                        return None
                    
                    await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Error de red en intento {attempt+1} de plantilla: {e}")
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(1.0)

    async def update_profile_picture(self, image_bytes: bytes, filename: str, mime_type: str, db: Optional[Any] = None) -> bool:
        """
        Sube una imagen usando Meta Resumable Upload API y actualiza la foto de perfil del número de WhatsApp.
        """
        access_token, phone_id = self.get_credentials(db)
        if not access_token or not phone_id:
            logger.error("WhatsAppService no está configurado.")
            return False

        # 1. Obtener App ID de forma dinámica desde el token
        app_id = None
        try:
            debug_url = f"https://graph.facebook.com/debug_token?input_token={access_token}&access_token={access_token}"
            async with httpx.AsyncClient() as client:
                debug_res = await client.get(debug_url, timeout=10.0)
                if debug_res.status_code == 200:
                    debug_data = debug_res.json()
                    app_id = debug_data.get("data", {}).get("app_id")
        except Exception as e:
            logger.error(f"Error obteniendo app_id desde Meta Token: {e}")

        if not app_id:
            logger.error("No se pudo extraer el App ID de Meta desde el token.")
            return False

        # 2. Inicializar sesión de subida (Resumable Upload)
        upload_url = f"https://graph.facebook.com/v18.0/{app_id}/uploads"
        params = {
            "file_name": filename,
            "file_length": len(image_bytes),
            "file_type": mime_type,
            "access_token": access_token
        }
        
        try:
            async with httpx.AsyncClient() as client:
                res = await client.post(upload_url, params=params, timeout=10.0)
                if res.status_code != 200:
                    logger.error(f"Error al iniciar subida en Meta: {res.text}")
                    return False
                
                session_id = res.json().get("id")
                if not session_id:
                    logger.error("No se recibió ID de sesión de subida desde Meta.")
                    return False

                # 3. Subir archivo binario
                session_url = f"https://graph.facebook.com/v18.0/{session_id}"
                headers = {
                    "Authorization": f"OAuth {access_token}",
                    "file_offset": "0",
                    "Content-Type": "application/octet-stream"
                }
                
                upload_res = await client.post(session_url, headers=headers, content=image_bytes, timeout=30.0)
                if upload_res.status_code != 200:
                    logger.error(f"Error al subir contenido a Meta: {upload_res.text}")
                    return False
                
                handle = upload_res.json().get("h")
                if not handle:
                    logger.error("No se recibió handle de archivo desde Meta.")
                    return False

                # 4. Actualizar perfil de WhatsApp con el handle
                profile_url = f"https://graph.facebook.com/v18.0/{phone_id}/whatsapp_business_profile"
                profile_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
                profile_payload = {
                    "messaging_product": "whatsapp",
                    "profile_picture_handle": handle
                }
                
                profile_res = await client.post(profile_url, headers=profile_headers, json=profile_payload, timeout=15.0)
                if profile_res.status_code != 200:
                    logger.error(f"Error al asignar foto de perfil en Meta: {profile_res.text}")
                    return False
                
                logger.info("Foto de perfil de WhatsApp comercial actualizada con éxito en Meta.")
                return True
        except Exception as e:
            logger.error(f"Excepción al actualizar foto de perfil de WhatsApp: {e}")
            return False

    async def upload_media(self, file_bytes: bytes, filename: str, mime_type: str, db: Optional[Any] = None) -> Optional[str]:
        """
        Sube un archivo de media a la API de Meta y retorna el media_id.
        """
        access_token, phone_id = self.get_credentials(db)
        if not access_token or not phone_id:
            logger.error("WhatsAppService no está configurado para subir media.")
            return None

        url = f"https://graph.facebook.com/v18.0/{phone_id}/media"
        headers = {
            "Authorization": f"Bearer {access_token}"
        }
        files = {
            "file": (filename, file_bytes, mime_type)
        }
        data = {
            "messaging_product": "whatsapp"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, files=files, data=data, timeout=30.0)
                response_data = response.json()
                if response.status_code == 200:
                    media_id = response_data.get("id")
                    logger.info(f"Archivo {filename} subido con éxito a Meta. Media ID: {media_id}")
                    return media_id
                
                logger.error(f"Error al subir media a Meta: {response.status_code}. Respuesta: {response_data}")
                return None
        except Exception as e:
            logger.error(f"Excepción al subir media a Meta: {e}")
            return None

    async def send_media_message(self, to_phone: str, media_id: str, media_type: str, caption: Optional[str] = None, filename: Optional[str] = None, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Envía un mensaje de tipo multimedia (image, audio, document, video) usando el media_id de Meta.
        """
        access_token, phone_id = self.get_credentials(db)
        if not access_token or not phone_id:
            logger.error("WhatsAppService no está configurado para enviar media.")
            return None

        url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        media_object = {"id": media_id}
        if caption and media_type in ["image", "video", "document"]:
            media_object["caption"] = caption
        if filename and media_type == "document":
            media_object["filename"] = filename

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": media_type,
            media_type: media_object
        }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(url, headers=headers, json=payload, timeout=15.0)
                    response_data = response.json()
                    if response.status_code == 200:
                        logger.info(f"Mensaje de media ({media_type}) enviado con éxito a {to_phone}")
                        return response_data
                    
                    logger.warning(f"Intento {attempt+1} de envío de media falló. Respuesta: {response_data}")
                    
                    is_transient = False
                    if isinstance(response_data, dict) and "error" in response_data:
                        err = response_data["error"]
                        is_transient = err.get("is_transient", False) or err.get("code") in [2, 4, 17, 368]
                    
                    if not is_transient or attempt == max_retries - 1:
                        return None
                    await asyncio.sleep(1.0)
            except Exception as e:
                logger.error(f"Error de red al enviar media: {e}")
                if attempt == max_retries - 1:
                    return None
                await asyncio.sleep(1.0)
        return None

    async def download_media(self, media_id: str, db: Optional[Any] = None) -> Optional[str]:
        """
        Obtiene la URL de descarga del media_id desde Meta Graph API y descarga el archivo temporalmente.
        Retorna la ruta local del archivo descargado.
        """
        access_token, _ = self.get_credentials(db)
        if not access_token:
            return None

        try:
            url_info = f"https://graph.facebook.com/v18.0/{media_id}"
            headers = {"Authorization": f"Bearer {access_token}"}
            async with httpx.AsyncClient() as client:
                res_info = await client.get(url_info, headers=headers, timeout=10.0)
                if res_info.status_code != 200:
                    logger.error(f"Error consultando URL de media ID {media_id}: {res_info.text}")
                    return None
                
                download_url = res_info.json().get("url")
                if not download_url:
                    return None

                res_file = await client.get(download_url, headers=headers, timeout=30.0)
                if res_file.status_code == 200:
                    temp_dir = os.path.join(os.getcwd(), "tmp_media")
                    os.makedirs(temp_dir, exist_ok=True)
                    local_path = os.path.join(temp_dir, f"{media_id}.ogg")
                    with open(local_path, "wb") as f:
                        f.write(res_file.content)
                    return local_path
        except Exception as e:
            logger.error(f"Excepción al descargar media {media_id}: {e}")
        return None

whatsapp_service = WhatsAppService()

