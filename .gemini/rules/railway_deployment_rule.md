---
description: REGLA INVIOLABLE DE DESPLIEGUE OBLIGATORIO EN RAILWAY TRAS MODIFICAR EL BACKEND
globs: backend/**/*
---

# REGLA OBLIGATORIA DE DESPLIEGUE EN RAILWAY PARA TODAS LAS IAS Y AGENTES

Cada vez que se modifique o cree cualquier archivo del backend (`backend/` o `backend/app/` or `backend/ai_agent/`):
1. DEBES realizar el `git add` y `git commit`.
2. DEBES ejecutar INMEDIATAMENTE `railway up --detach` en la carpeta `backend` mediante la herramienta de comandos.
3. DEBES verificar que el servidor retorne HTTP Status 200 OK antes de dar por terminada la tarea.

¡ESTÁ TERMINANTEMENTE PROHIBIDO DAR POR FINALIZADA UNA TAREA DEL BACKEND SIN EJECUTAR `railway up --detach` Y CONFIRMAR EL DESPLIEGUE!
