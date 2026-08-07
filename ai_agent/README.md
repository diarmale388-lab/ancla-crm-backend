# 🤖 Sofi AI Module (`/ai_agent`) - ANCLA CRM

Módulo de Inteligencia Artificial 100% independiente, desacoplado y autónomo basado en **LangGraph**, **OpenRouter** y **FastAPI**.

---

## 🏛️ Principios de Arquitectura

1. **Separación Estricta de Responsabilidades (Separation of Concerns)**:
   - Todo el código del agente de IA reside en `backend/ai_agent/`.
   - **CERO modificaciones** a los controladores, esquemas o modelos de la base de datos SQL del CRM transaccional.

2. **Enrutamiento Multi-Modelo vía OpenRouter**:
   - `classifier_node`: Clasificación ultra-rápida de intenciones con `google/gemini-3.5-flash-lite`.
   - `sales_expert_node`: Agente comercial avanzado para persuasión, empatía y objeciones con `anthropic/claude-3.5-sonnet`.

3. **Aislamiento de Sesión por Hilo (`thread_id`)**:
   - Cada conversación utiliza el **número telefónico del cliente (`phone`)** como `thread_id` en el checkpointer de LangGraph.

4. **Compuerta de Control `chatbot_enabled`**:
   - Si `chatbot_enabled == False`, el grafo finaliza inmediatamente (`END`) sin consumir tokens de LLM.

5. **Interfaces Limpias (`@tool` Bridges)**:
   - En `ai_agent/tools.py` se encuentran las funciones asíncronas `@tool` decoradas. El equipo del CRM solo necesita implementar la lógica del ORM/SQL dentro de cada función sin alterar el grafo.

---

## 📂 Estructura del Módulo

```text
backend/ai_agent/
├── __init__.py               # Paquete independiente
├── config.py                 # Ajustes OpenRouter y modelos
├── state.py                  # AgentState (TypedDict con thread_id = phone)
├── tools.py                  # Interfaces @tool vacías para implementación CRM
├── prompts.py                # Reglas inviolables de Sofi AI (Contrato Sofi)
├── nodes/                    # Nodos de LangGraph
│   ├── classifier.py         # Gemini Flash Lite
│   ├── sales_expert.py       # Claude 3.5 Sonnet
│   ├── simple_interaction.py # Saludos y respuestas rápidas
│   └── tool_executor.py      # Ejecutor de herramientas
├── graph.py                  # StateGraph compilado con MemorySaver
├── router.py                 # API Router FastAPI (/api/v1/ai)
├── test_agent.py             # Script de pruebas autónomas
└── README.md                 # Guía de uso
```

---

## 🚀 Integración en `main.py` de FastAPI (Opcional y Limpia)

Para habilitar el endpoint de Sofi AI en la aplicación FastAPI principal del CRM, el equipo del CRM solo debe añadir 2 líneas en `backend/app/main.py`:

```python
from ai_agent.router import router as ai_router

app.include_router(ai_router)
```

---

## 🛠️ Cómo implementar las herramientas CRM en `ai_agent/tools.py`

Edite `ai_agent/tools.py` reemplazando los retornos ficticios por las consultas reales a SQLAlchemy / DB:

```python
@tool
async def save_appointment(phone: str, user_name: str, date: str, time: str, modality: str, email: str = None):
    # Inyectar llamada a db.add(Appointment(...))
    return {"success": True, "appointment_id": "APP-12345"}
```
