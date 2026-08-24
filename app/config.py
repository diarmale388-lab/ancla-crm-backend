import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "CRM Omnicanal Antigravity"
    API_V1_STR: str = "/api/v1"

    # URL pública base del backend (usada para construir enlaces absolutos, ej. PDFs de propuestas).
    # NUNCA debe apuntar a localhost en producción: se configura vía variable de entorno por despliegue.
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "https://ancla-crm-backend-production.up.railway.app")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./crm.db")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://default:fLedMAtmksxQSTEuQSlcldXzCvTbsNuD@redis.railway.internal:6379")
    
    # Security / JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-production-1234567890")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Meta / WhatsApp Integration
    META_APP_ID: Optional[str] = os.getenv("META_APP_ID")
    META_APP_SECRET: Optional[str] = os.getenv("META_APP_SECRET")
    META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "antigravity_verify_token_123")
    META_ACCESS_TOKEN: Optional[str] = os.getenv("META_ACCESS_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "1309006675619043")
    WHATSAPP_BUSINESS_ACCOUNT_ID: Optional[str] = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
    
    # AI Engine
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    
    # SMS Integration (Ejemplo: Twilio)
    TWILIO_ACCOUNT_SID: Optional[str] = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN: Optional[str] = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER: Optional[str] = os.getenv("TWILIO_FROM_NUMBER")
    
    # OpenRouter API Key
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    
    # WebPush VAPID Keys
    VAPID_PUBLIC_KEY: str = os.getenv(
        "VAPID_PUBLIC_KEY",
        "BLr7V7hzd1eU7ZZbckJfDOS6ylJ3HuEo1JDyLeFauAwYJmhAyqubMHe9y1rmEJSjGJbMjvlSFTF0241kJk0lgA0"
    )
    VAPID_PRIVATE_KEY: str = os.getenv(
        "VAPID_PRIVATE_KEY",
        "-----BEGIN PRIVATE KEY-----\nMIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgP3aYzcwB12kW2lxN\nlyFFDHbJHMCvqysWDOcyKTo/2ymhRANCAAS6+1e4c3dXlO2WW3JCXwzkuspSdx7h\nKNSQ8i3hWrgMGCZoQMqrmzB3vcta5hCUoxiWzI75UhUxdNuNZCZNJYAN\n-----END PRIVATE KEY-----"
    )
    VAPID_PRIVATE_KEY_PATH: Optional[str] = os.getenv("VAPID_PRIVATE_KEY_PATH", "vapid_private.pem")
    VAPID_CLAIM_EMAIL: str = os.getenv("VAPID_CLAIM_EMAIL", "mailto:soporte@anclaprojects.com")

    class Config:
        case_sensitive = True
        env_file = ".env"
        extra = "ignore"

settings = Settings()
