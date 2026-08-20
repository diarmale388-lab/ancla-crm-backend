"""
ai_agent/router.py
------------------
Endpoint FastAPI dedicado e independiente para el módulo Sofi AI.
Permite invocar el grafo de LangGraph de forma asíncrona enviando el número de teléfono
como thread_id de sesión.
"""

from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from langchain_core.messages import HumanMessage
import logging

from ai_agent.graph import sofi_ai_agent
from app.core.rate_limiter import rate_limit

logger = logging.getLogger("ai_agent_router")

router = APIRouter(prefix="/api/v1/ai", tags=["Sofi AI Agent"])


class AIChatRequest(BaseModel):
    phone: str = Field(..., description="Número telefónico del cliente (sirve como thread_id)")
    message: str = Field(..., description="Contenido del mensaje enviado por el cliente")
    chatbot_enabled: bool = Field(True, description="Flag de activación del chatbot entregado por CRM Core")
    user_name: Optional[str] = Field(None, description="Nombre opcional del cliente si ya se conoce")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadatos contextuales adicionales")


class AIChatResponse(BaseModel):
    phone: str
    chatbot_enabled: bool
    response: Optional[str]
    intent: Optional[str]
    requires_human: bool
    executed_tools: List[str] = []


@router.post("/chat", response_model=AIChatResponse)
@rate_limit(max_requests=30, window_seconds=60, key_prefix="ai_chat")
async def chat_with_sofi(request_http: Request, request: AIChatRequest):
    """
    Endpoint principal para interactuar con Sofi AI con protección de Rate Limiting y Trazabilidad.
    """
    if not request.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El campo 'phone' es obligatorio para aislar la sesión."
        )
        
    # Definir la configuración de sesión en LangGraph (thread_id = phone)
    config = {
        "configurable": {
            "thread_id": request.phone
        }
    }
    
    # Preparar el estado de entrada
    input_state = {
        "messages": [HumanMessage(content=request.message)],
        "phone": request.phone,
        "chatbot_enabled": request.chatbot_enabled,
        "user_name": request.user_name,
        "requires_human": False,
        "metadata": request.metadata or {}
    }
    
    try:
        # Ejecutar el grafo de forma asíncrona
        final_state = await sofi_ai_agent.ainvoke(input_state, config=config)
        
        # Extraer la última respuesta de la IA
        messages = final_state.get("messages", [])
        last_ai_message = None
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "ai":
                last_ai_message = msg.content
                break
            elif isinstance(msg, dict) and msg.get("role") == "assistant":
                last_ai_message = msg.get("content")
                break
                
        return AIChatResponse(
            phone=request.phone,
            chatbot_enabled=request.chatbot_enabled,
            response=last_ai_message if request.chatbot_enabled else "Chatbot desactivado para esta sesión.",
            intent=final_state.get("intent"),
            requires_human=final_state.get("requires_human", False),
            executed_tools=[]
        )
    except Exception as e:
        logger.error(f"Error ejecutando Sofi AI Agent para {request.phone}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno procesando la respuesta del agente IA."
        )



@router.get("/health")
async def ai_agent_health():
    """
    Endpoint de monitoreo de salud del módulo Sofi AI.
    """
    return {
        "status": "healthy",
        "module": "Sofi AI (/ai_agent)",
        "isolation": "100% Independent",
        "router": "OpenRouter Multi-Model"
    }
