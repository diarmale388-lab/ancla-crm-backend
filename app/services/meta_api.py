import logging
import httpx
import random
from typing import Dict, Any, Optional
from app.config import settings

logger = logging.getLogger("meta_api_service")

# El token real de Meta ya NO se hardcodea en el código fuente: se lee exclusivamente
# desde la variable de entorno META_ACCESS_TOKEN (ver backend/.env / app/config.py).
# Si no está configurada, el sistema queda sin token por defecto (fail-safe) en vez de
# usar un token real embebido en el repositorio.
VERIFIED_META_TOKEN = settings.META_ACCESS_TOKEN

class MetaApiService:
    def get_token(self, db: Optional[Any] = None) -> Optional[str]:
        token = VERIFIED_META_TOKEN
        if db:
            try:
                from app.models.base import SystemSetting
                tok = db.query(SystemSetting).filter(SystemSetting.key == "meta_access_token").first()
                if tok and tok.value and len(tok.value.strip()) > 30:
                    token = tok.value.strip()
            except Exception:
                pass
        return token

    def __init__(self):
        self.api_version = "v18.0"
        self.base_url = f"https://graph.facebook.com/{self.api_version}"

    async def fetch_leadgen_details(self, leadgen_id: str, db: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Obtiene la información completa del lead (nombre, teléfono, correo, respuestas del formulario)
        desde Meta Graph API usando su leadgen_id.
        """
        token = self.get_token(db)
        if not token:
            logger.error("Falta Meta Access Token para consultar leadgen_id.")
            return None

        url = f"https://graph.facebook.com/v18.0/{leadgen_id}"
        headers = {
            "Authorization": f"Bearer {token}"
        }

        try:
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=headers, timeout=10.0)
                if res.status_code == 200:
                    data = res.json()
                    logger.info(f"Leadgen details recuperados exitosamente desde Meta para leadgen_id={leadgen_id}")
                    return data
                else:
                    logger.error(f"Error consultando leadgen_id {leadgen_id} en Meta ({res.status_code}): {res.text}")
                    return None
        except Exception as e:
            logger.error(f"Excepción consultando leadgen_id {leadgen_id}: {e}")
            return None

    async def send_instagram_dm(self, recipient_psid: str, message_text: str) -> Optional[Dict[str, Any]]:
        """
        Envía un DM directo de Instagram a un usuario específico usando su Page-Scoped ID (PSID).
        """
        if not self.access_token:
            logger.error("MetaApiService no está configurado (falta Meta Access Token).")
            return None

        url = f"{self.base_url}/me/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "recipient": {
                "id": recipient_psid
            },
            "message": {
                "text": message_text
            }
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                response_data = response.json()
                if response.status_code != 200:
                    logger.error(f"Error en Instagram Graph API DM: {response_data}")
                    return None
                logger.info(f"Mensaje enviado con éxito por Instagram DM a {recipient_psid}")
                return response_data
        except Exception as e:
            logger.error(f"Error de red al enviar Instagram DM: {e}")
            return None

    async def reply_to_comment(self, comment_id: str, message_text: str) -> Optional[Dict[str, Any]]:
        """
        Responde a un comentario público en un post de Instagram o Facebook de forma pública.
        """
        if not self.access_token:
            logger.error("MetaApiService no está configurado.")
            return None

        url = f"{self.base_url}/{comment_id}/replies"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "message": message_text
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                response_data = response.json()
                if response.status_code != 200:
                    logger.error(f"Error respondiendo al comentario {comment_id}: {response_data}")
                    return None
                logger.info(f"Comentario {comment_id} respondido públicamente.")
                return response_data
        except Exception as e:
            logger.error(f"Error de red al responder comentario: {e}")
            return None


    # --- Métodos de Meta Marketing API (Ads) ---

    async def create_campaign(self, name: str, objective: str, budget: float) -> Optional[str]:
        """
        Crea una campaña de anuncios en Meta Ads y devuelve el ID único de la campaña.
        Si no hay token, la simula de forma realista.
        """
        if not self.access_token:
            logger.warning("[SIMULADO META ADS] Creando campaña publicitaria en Meta de forma local.")
            # Generar un ID de Meta Ads simulado
            simulated_id = f"act_10203040_{random.randint(100000000, 999999999)}"
            return simulated_id

        # En producción real se consultaría la cuenta de anuncios (Ad Account)
        # Endpoint: POST /act_{ad_account_id}/campaigns
        # Pero requiere configurar settings.META_AD_ACCOUNT_ID
        ad_account_id = "me"  # O un valor dinámico
        url = f"{self.base_url}/{ad_account_id}/campaigns"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "name": name,
            "objective": objective,
            "status": "PAUSED",  # Por seguridad la creamos pausada
            "daily_budget": int(budget * 100),  # Meta Ads trabaja presupuestos en centavos
            "special_ad_categories": "NONE"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                response_data = response.json()
                if response.status_code != 200:
                    logger.error(f"Error creando campaña en Meta: {response_data}")
                    return None
                return response_data.get("id")
        except Exception as e:
            logger.error(f"Error de red al crear campaña en Meta: {e}")
            return None

    async def update_campaign_status(self, meta_campaign_id: str, new_status: str) -> bool:
        """
        Modifica el estado de una campaña en Meta Ads (ACTIVE, PAUSED).
        """
        if not self.access_token:
            logger.warning(f"[SIMULADO META ADS] Actualizando estado de campaña {meta_campaign_id} a {new_status}.")
            return True

        url = f"{self.base_url}/{meta_campaign_id}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "status": new_status
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, headers=headers, json=payload, timeout=10.0)
                response_data = response.json()
                if response.status_code != 200 or not response_data.get("success"):
                    logger.error(f"Error actualizando estado de campaña en Meta: {response_data}")
                    return False
                return True
        except Exception as e:
            logger.error(f"Error de red al actualizar campaña en Meta: {e}")
            return False

    async def get_campaign_metrics(self, meta_campaign_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene insights y rendimiento publicitario de la campaña.
        Si no hay token, simula métricas fluctuantes e inteligentes.
        """
        if not self.access_token:
            # Simular métricas realistas basadas en el ID
            impressions = random.randint(1000, 15000)
            clicks = int(impressions * random.uniform(0.015, 0.05))  # CTR de 1.5% a 5%
            spend = clicks * random.uniform(0.2, 0.8)  # CPC de $0.20 a $0.80 USD
            leads = int(clicks * random.uniform(0.1, 0.25))  # Conversión del 10% al 25%
            
            # Retorno
            return {
                "impressions": impressions,
                "clicks": clicks,
                "spend": round(spend, 2),
                "leads_count": leads
            }

        # En producción
        # Endpoint: GET /{campaign_id}/insights?fields=impressions,clicks,spend
        url = f"{self.base_url}/{meta_campaign_id}/insights"
        params = {
            "access_token": self.access_token,
            "fields": "impressions,clicks,spend"
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=10.0)
                response_data = response.json()
                if response.status_code != 200:
                    logger.error(f"Error consultando insights de campaña en Meta: {response_data}")
                    return None
                
                data_list = response_data.get("data", [])
                if not data_list:
                    return {
                        "impressions": 0,
                        "clicks": 0,
                        "spend": 0.0,
                        "leads_count": 0
                    }
                
                insights = data_list[0]
                return {
                    "impressions": int(insights.get("impressions", 0)),
                    "clicks": int(insights.get("clicks", 0)),
                    "spend": float(insights.get("spend", 0.0)),
                    "leads_count": 0  # Se sincroniza dinámicamente con los leads locales en el router
                }
        except Exception as e:
            logger.error(f"Error de red al consultar insights en Meta: {e}")
            return None

meta_api_service = MetaApiService()
