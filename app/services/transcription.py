import os
import logging
import asyncio
import httpx

logger = logging.getLogger(__name__)

async def transcribe_audio_file(file_path: str) -> str:
    """
    Transcribe un archivo de audio (.ogg, .opus, .mp3, .wav, .m4a) enviado por WhatsApp a texto en español.
    Utiliza OpenAI Whisper API o Gemini Multimodal Audio API.
    """
    if not os.path.exists(file_path):
        logger.error(f"Transcripción cancelada: El archivo {file_path} no existe.")
        return ""

    openai_key = os.getenv("OPENAI_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")

    # 1. OpenAI Whisper API
    if openai_key:
        try:
            url = "https://api.openai.com/v1/audio/transcriptions"
            headers = {"Authorization": f"Bearer {openai_key}"}
            with open(file_path, "rb") as audio_file:
                files = {"file": (os.path.basename(file_path), audio_file, "audio/ogg")}
                data = {"model": "whisper-1", "language": "es"}
                async with httpx.AsyncClient() as client:
                    res = await client.post(url, headers=headers, files=files, data=data, timeout=30.0)
                    if res.status_code == 200:
                        transcript = res.json().get("text", "").strip()
                        if transcript:
                            logger.info(f"✅ Transcripción exitosa con Whisper: '{transcript}'")
                            return transcript
        except Exception as e:
            logger.error(f"Error transcribiendo con OpenAI Whisper: {e}")

    # OpenRouter Multimodal Audio API Fallback
    openrouter_key = os.getenv("OPENROUTER_API_KEY") or getattr(settings, "OPENROUTER_API_KEY", "")
    if openrouter_key:
        try:
            import base64
            with open(file_path, "rb") as f:
                b64_audio = base64.b64encode(f.read()).decode("utf-8")

            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://anclaspecialprojects.com",
                "X-Title": "ANCLA CRM - Sofi AI Module"
            }
            payload = {
                "model": "google/gemini-2.5-flash",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcribe el contenido exacto de este audio de WhatsApp en español. Devuelve ÚNICAMENTE el texto transcripto, sin comentarios adicionales."},
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
                        logger.info(f"✅ Transcripción exitosa con OpenRouter Audio: '{transcript}'")
                        return transcript
        except Exception as e_or:
            logger.error(f"Error transcribiendo con OpenRouter Audio: {e_or}")

    return ""
