import logging
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, Dict, Any

logger = logging.getLogger("email_service")

class EmailService:
    def send_email_with_attachment(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        attachment_path: Optional[str] = None,
        attachment_name: Optional[str] = None,
        smtp_settings: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Envía un correo electrónico utilizando un servidor SMTP configurado dinámicamente.
        Soporta archivos adjuntos (como el PDF de propuesta).
        """
        if not smtp_settings:
            logger.error("No se proporcionó configuración SMTP.")
            return False
            
        host = smtp_settings.get("host")
        port = smtp_settings.get("port")
        username = smtp_settings.get("username")
        password = smtp_settings.get("password")
        sender_email = smtp_settings.get("sender_email")
        sender_name = smtp_settings.get("sender_name") or "CRM Antigravity"
        
        if not all([host, port, username, password, sender_email]):
            logger.error(f"Configuración SMTP incompleta: {smtp_settings}")
            return False
            
        try:
            # Convertir puerto a int si es str
            port = int(port)
        except ValueError:
            logger.error(f"Puerto SMTP no es válido: {port}")
            return False

        # Configurar el mensaje
        msg = MIMEMultipart()
        msg['From'] = f"{sender_name} <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Cuerpo del mensaje
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        
        # Adjuntar archivo si existe
        if attachment_path and os.path.exists(attachment_path):
            try:
                filename = attachment_name or os.path.basename(attachment_path)
                with open(attachment_path, "rb") as f:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(f.read())
                    
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    f"attachment; filename= {filename}",
                )
                msg.attach(part)
                logger.info(f"Archivo adjunto cargado exitosamente: {attachment_path}")
            except Exception as e:
                logger.error(f"Error cargando archivo adjunto {attachment_path}: {e}")
                
        # Conectar al servidor SMTP y enviar
        try:
            # Determinar si usar SSL o TLS según el puerto estándar
            # Generalmente 465 es SSL, 587 es STARTTLS
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=10.0)
            else:
                server = smtplib.SMTP(host, port, timeout=10.0)
                server.ehlo()
                # Activar cifrado TLS si el puerto soporta STARTTLS
                if port == 587 or server.has_extn("STARTTLS"):
                    server.starttls()
                    server.ehlo()
            
            # Autenticarse
            server.login(username, password)
            # Enviar
            server.sendmail(sender_email, to_email, msg.as_string())
            server.close()
            logger.info(f"Correo electrónico enviado con éxito a {to_email}")
            return True
        except Exception as e:
            logger.error(f"Error de conexión o envío SMTP hacia {to_email}: {e}")
            return False

email_service = EmailService()
