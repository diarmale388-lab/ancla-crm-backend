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

class AIAgentSettings(BaseSettings):
    # Claves de API para OpenRouter
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY") or getattr(settings, "OPENROUTER_API_KEY", "") or ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    
    CLASSIFIER_MODEL: str = os.getenv("AI_CLASSIFIER_MODEL", "google/gemini-2.5-flash")
    SALES_EXPERT_MODEL: str = os.getenv("AI_SALES_EXPERT_MODEL", "anthropic/claude-3.5-sonnet")


    
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
