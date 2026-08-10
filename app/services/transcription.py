import os
import logging
import asyncio
import base64
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

async def transcribe_audio_bytes(audio_bytes: bytes) -> str:
    """
    Transcribe bytes de audio (.ogg, .opus, .mp3, .wav, .m4a) recibido por WhatsApp a texto en español.
    Utiliza OpenRouter Gemini Multimodal Audio API o OpenAI Whisper API.
    """
    if not audio_bytes:
        logger.error("Transcripción cancelada: Bytes de audio vacíos.")
        return ""

    try:
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        
        # 1. OpenRouter (Google Gemini 2.5 Flash Multimodal Audio)
        openrouter_key = os.getenv("OPENROUTER_API_KEY") or getattr(settings, "OPENROUTER_API_KEY", "")
        if openrouter_key:
            try:
                url = "https://openrouter.ai/api/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://anclaspecialprojects.com",
                    "X-Title": "ANCLA CRM - Sofi Audio Transcriber"
                }
                payload = {
                    "model": "google/gemini-2.5-flash",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text", 
                                    "text": "Transcribe exactamente el contenido de este audio de voz en español. Devuelve ÚNICAMENTE el texto transcripto, sin comillas ni aclaraciones."
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
                            logger.info(f"✅ Transcripción exitosa con OpenRouter Gemini: '{transcript}'")
                            return transcript
                    else:
                        logger.warning(f"Fallo OpenRouter Audio (Status {res.status_code}): {res.text}")
            except Exception as e_or:
                logger.error(f"Error en OpenRouter Audio transcription: {e_or}")

        # 2. OpenAI Whisper API
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


async def transcribe_audio_file(file_path: str) -> str:
    """
    Transcribe un archivo de audio (.ogg, .opus, .mp3, .wav, .m4a) leyendo los bytes de disco.
    """
    if not os.path.exists(file_path):
        logger.error(f"Transcripción cancelada: El archivo {file_path} no existe.")
        return ""

    try:
        with open(file_path, "rb") as f:
            audio_bytes = f.read()
        return await transcribe_audio_bytes(audio_bytes)
    except Exception as e:
        logger.error(f"Error leyendo archivo en transcribe_audio_file: {e}")
        return ""
