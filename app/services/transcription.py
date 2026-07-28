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

    # 2. Gemini Multimodal Audio API
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            audio_file = genai.upload_file(path=file_path)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = "Transcribe el contenido exacto de este audio de WhatsApp en español. Devuelve ÚNICAMENTE el texto transcripto, sin comentarios adicionales."
            response = await asyncio.to_thread(model.generate_content, [prompt, audio_file])
            transcript = response.text.strip()
            if transcript:
                logger.info(f"✅ Transcripción exitosa con Gemini Audio: '{transcript}'")
                return transcript
        except Exception as e:
            logger.error(f"Error transcribiendo con Gemini Audio: {e}")

    return ""
