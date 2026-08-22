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


async def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg", db=None) -> str:
    """
    Transcribe bytes de audio (.ogg, .opus, .mp3, .wav, .m4a) recibido por WhatsApp a texto en español.
    Utiliza OpenAI Whisper Large-v3 vía OpenRouter con failover a GPT-Audio-Mini y OpenAI Whisper directo.
    """
    if not audio_bytes or len(audio_bytes) < 10:
        logger.warning("Transcripción cancelada: Bytes de audio vacíos o insuficientes.")
        return ""

    openrouter_key = get_openrouter_api_key(db)

    # 1. TIER 1: OpenRouter Dedicated Audio Transcriptions API (OpenAI Whisper Large-v3)
    if openrouter_key:
        whisper_models = ["openai/whisper-large-v3", "openai/whisper-1"]
        for w_model in whisper_models:
            try:
                url = "https://openrouter.ai/api/v1/audio/transcriptions"
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "HTTP-Referer": "https://anclaspecialprojects.com",
                    "X-Title": "ANCLA CRM - Sofi Audio Whisper"
                }
                filename = "audio.ogg" if "ogg" in mime_type or "opus" in mime_type else "audio.wav"
                files = {"file": (filename, audio_bytes, mime_type)}
                data = {"model": w_model, "language": "es"}
                
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, headers=headers, files=files, data=data, timeout=20.0)
                    if res.status_code == 200:
                        res_json = res.json()
                        transcript = res_json.get("text", "").strip()
                        if transcript:
                            logger.info(f"✅ Transcripción exitosa con OpenRouter ({w_model}): '{transcript}'")
                            return transcript
                    else:
                        logger.warning(f"Fallo en OpenRouter {w_model} (Status {res.status_code}): {res.text[:120]}")
            except Exception as e_w:
                logger.error(f"Excepción en OpenRouter Whisper {w_model}: {e_w}")

        # 2. TIER 2: Multimodal Chat API (OpenAI GPT-Audio-Mini / Gemini con input_audio)
        try:
            b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
            fmt = "ogg" if "ogg" in mime_type or "opus" in mime_type else "wav"
            
            chat_url = "https://openrouter.ai/api/v1/chat/completions"
            chat_headers = {
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://anclaspecialprojects.com",
                "X-Title": "ANCLA CRM - Sofi Audio Multimodal"
            }
            chat_payload = {
                "model": "openai/gpt-audio-mini",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Transcribe exactamente el contenido de este audio de voz en español. Devuelve ÚNICAMENTE el texto transcripto, sin comentarios adicionales ni comillas."
                            },
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": b64_audio,
                                    "format": fmt
                                }
                            }
                        ]
                    }
                ]
            }
            async with httpx.AsyncClient() as client:
                res = await client.post(chat_url, json=chat_payload, headers=chat_headers, timeout=25.0)
                if res.status_code == 200:
                    data = res.json()
                    transcript = data["choices"][0]["message"]["content"].strip()
                    if transcript and not transcript.startswith("Error") and len(transcript) > 1:
                        logger.info(f"✅ Transcripción exitosa con gpt-audio-mini: '{transcript}'")
                        return transcript
        except Exception as e_chat:
            logger.error(f"Excepción en OpenRouter gpt-audio-mini: {e_chat}")

    # 3. TIER 3: OpenAI Direct Whisper API (si está configurada)
    openai_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", "")
    if openai_key:
        try:
            url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {openai_key}"}
            files = {"file": ("audio.ogg", audio_bytes, "audio/ogg")}
            data = {"model": "whisper-1", "language": "es"}
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, files=files, data=data, timeout=25.0)
                if res.status_code == 200:
                    transcript = res.json().get("text", "").strip()
                    if transcript:
                        logger.info(f"✅ Transcripción exitosa con OpenAI Whisper Directo: '{transcript}'")
                        return transcript
        except Exception as e_direct:
            logger.error(f"Error transcribiendo con OpenAI Whisper Directo: {e_direct}")

    return ""


async def transcribe_audio_file(file_path: str, db=None) -> str:
    """
    Transcribe un archivo de audio (.ogg, .opus, .mp3, .wav, .m4a) leyendo los bytes de disco.
    """
    if not os.path.exists(file_path):
        logger.error(f"Transcripción cancelada: El archivo {file_path} no existe.")
        return ""

    try:
        mime = "audio/ogg" if file_path.endswith((".ogg", ".opus")) else "audio/wav"
        with open(file_path, "rb") as f:
            audio_bytes = f.read()
        return await transcribe_audio_bytes(audio_bytes, mime_type=mime, db=db)
    except Exception as e:
        logger.error(f"Error leyendo archivo en transcribe_audio_file: {e}")
        return ""
