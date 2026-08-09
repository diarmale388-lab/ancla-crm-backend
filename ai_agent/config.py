"""
ai_agent/config.py
------------------
Configuración centralizada para el módulo Sofi AI.
Utiliza OpenRouter para enrutamiento multi-modelo independiente del CRM Core.
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


from app.config import settings

def get_dynamic_openrouter_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if key and len(key) > 20:
        return key
    try:
        from app.database import SessionLocal
        from app.models.base import SystemSetting
        db = SessionLocal()
        s = db.query(SystemSetting).filter(SystemSetting.key.in_(["gemini_api_key", "openrouter_api_key"])).first()
        db_key = s.value if s and s.value else ""
        db.close()
        return db_key
    except Exception:
        return ""

class AIAgentSettings(BaseSettings):
    # Claves de API para OpenRouter
    OPENROUTER_API_KEY: str = get_dynamic_openrouter_key()
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    
    CLASSIFIER_MODEL: str = os.getenv("AI_CLASSIFIER_MODEL", "openai/gpt-4o-mini")
    SALES_EXPERT_MODEL: str = os.getenv("AI_SALES_EXPERT_MODEL", "openai/gpt-4o")



    
    # Parámetros de timeout y reintentos
    REQUEST_TIMEOUT: float = 15.0
    MAX_RETRIES: int = 2
    
    # Encabezados requeridos por OpenRouter
    HTTP_REFERER: str = "https://ancla-crm.com"
    SITE_NAME: str = "ANCLA CRM - Sofi AI Module"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


ai_settings = AIAgentSettings()
