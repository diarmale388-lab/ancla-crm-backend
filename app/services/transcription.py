import os
import logging
import asyncio
import base64
import httpx
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)

def get_openrouter_api_key(db=None) -> str:
    """
    Obtiene la clave de OpenRouter de forma ultra-robusta buscando en múltiples fuentes:
    1. Variable de entorno OPENROUTER_API_KEY
    2. settings.OPENROUTER_API_KEY
    3. settings.GEMINI_API_KEY (si empieza por sk-or-v1)
    4. os.getenv("GEMINI_API_KEY")
    5. Base de datos PostgreSQL (tabla SystemSetting)
    """
    key = os.getenv("OPENROUTER_API_KEY") or getattr(settings, "OPENROUTER_API_KEY", "") or ""
    if not key and getattr(settings, "GEMINI_API_KEY", "").startswith("sk-or-v1"):
        key = settings.GEMINI_API_KEY
    if not key and os.getenv("GEMINI_API_KEY", "").startswith("sk-or-v1"):
        key = os.getenv("GEMINI_API_KEY")
    if not key:
        try:
            from app.database import SessionLocal
            from app.models.base import SystemSetting
            session = db or SessionLocal()
            rows = session.query(SystemSetting).filter(
                SystemSetting.key.in_(["openrouter_api_key", "gemini_api_key"])
            ).all()
            for r in rows:
                if r.value and r.value.startswith("sk-or-v1"):
                    key = r.value
                    break
            if not db and session:
                session.close()
        except Exception as e:
            logger.error(f"Error consultando clave en SystemSetting: {e}")
    return key.strip() if key else ""


async def transcribe_audio_bytes(audio_bytes: bytes, db=None) -> str:
    """
    Transcribe bytes de audio (.ogg, .opus, .mp3, .wav, .m4a) recibido por WhatsApp a texto en español.
    Utiliza Google Gemini 2.5 Flash Multimodal Audio vía OpenRouter con failover a Gemini 2.0 Flash y Whisper.
    """
    if not audio_bytes:
        logger.error("Transcripción cancelada: Bytes de audio vacíos.")
        return ""

    try:
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        openrouter_key = get_openrouter_api_key(db)

        # 1. Intentar con OpenRouter (Google Gemini 2.5 Flash / 2.0 Flash Multimodal Audio)
        if openrouter_key:
            for model_name in ["google/gemini-2.5-flash", "google/gemini-2.0-flash-001"]:
                try:
                    url = "https://openrouter.ai/api/v1/chat/completions"
                    headers = {
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://anclaspecialprojects.com",
                        "X-Title": "ANCLA CRM - Sofi Audio Transcriber"
                    }
                    payload = {
                        "model": model_name,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text", 
                                        "text": "Transcribe exactamente el contenido de este audio de voz en español. Devuelve ÚNICAMENTE el texto transcripto, sin explicaciones ni comillas."
                                    },
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:audio/ogg;base64,{b64_audio}"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                    async with httpx.AsyncClient() as client:
                        res = await client.post(url, json=payload, headers=headers, timeout=25.0)
                        if res.status_code == 200:
                            data = res.json()
                            transcript = data["choices"][0]["message"]["content"].strip()
                            if transcript:
                                logger.info(f"✅ Transcripción exitosa con {model_name}: '{transcript}'")
                                return transcript
                        else:
                            logger.warning(f"Fallo OpenRouter con {model_name} (Status {res.status_code}): {res.text[:100]}")
                except Exception as e_or:
                    logger.error(f"Error en OpenRouter {model_name}: {e_or}")

        # 2. Intentar con OpenAI Whisper API (si está configurada)
        openai_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", "")
        if openai_key:
            try:
                url = "https://api.openai.com/v1/audio/transcriptions"
                headers = {"Authorization": f"Bearer {openai_key}"}
                files = {"file": ("audio.ogg", audio_bytes, "audio/ogg")}
                data = {"model": "whisper-1", "language": "es"}
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, headers=headers, files=files, data=data, timeout=30.0)
                    if res.status_code == 200:
                        transcript = res.json().get("text", "").strip()
                        if transcript:
                            logger.info(f"✅ Transcripción exitosa con OpenAI Whisper: '{transcript}'")
                            return transcript
            except Exception as e_w:
                logger.error(f"Error transcribiendo con OpenAI Whisper: {e_w}")

    except Exception as e:
        logger.error(f"Error general en transcribe_audio_bytes: {e}")

    return ""


async def transcribe_audio_file(file_path: str, db=None) -> str:
    """
    Transcribe un archivo de audio (.ogg, .opus, .mp3, .wav, .m4a) leyendo los bytes de disco.
    """
    if not os.path.exists(file_path):
        logger.error(f"Transcripción cancelada: El archivo {file_path} no existe.")
        return ""

    try:
        with open(file_path, "rb") as f:
            audio_bytes = f.read()
        return await transcribe_audio_bytes(audio_bytes, db=db)
    except Exception as e:
        logger.error(f"Error leyendo archivo en transcribe_audio_file: {e}")
        return ""
