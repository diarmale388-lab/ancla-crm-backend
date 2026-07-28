import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("sms_service")

class SMSService:
    def __init__(self):
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_number = settings.TWILIO_FROM_NUMBER

    async def send_sms(self, to_phone: str, message_text: str) -> bool:
        """
        Envía un SMS usando Twilio si las credenciales están configuradas.
        De lo contrario, simula el envío y lo registra en los logs.
        """
        if not self.account_sid or not self.auth_token or not self.from_number:
            logger.warning(
                f"[SIMULADO SMS] No se configuró Twilio. Enviando a {to_phone}: {message_text}"
            )
            return True

        # Importación tardía por si acaso
        try:
            # Si el usuario configura las credenciales de Twilio, podemos importar twilio
            # e intentar hacer la llamada. En caso contrario, lo simulamos para no romper.
            from twilio.rest import Client
            client = Client(self.account_sid, self.auth_token)
            
            message = client.messages.create(
                body=message_text,
                from_=self.from_number,
                to=to_phone
            )
            logger.info(f"SMS enviado con éxito vía Twilio. SID: {message.sid}")
            return True
        except ImportError:
            logger.warning(
                f"[SIMULADO SMS] (Instala 'twilio' para envío real) Enviando a {to_phone}: {message_text}"
            )
            return True
        except Exception as e:
            logger.error(f"Error al enviar SMS vía Twilio: {e}")
            return False

sms_service = SMSService()
