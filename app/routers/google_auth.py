import logging
import httpx
from datetime import datetime, timedelta
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.base import User, SystemSetting
from app.routers.auth import get_current_user
from app.config import settings
from app.core.crypto import encrypt_value, decrypt_value

logger = logging.getLogger("google_auth_router")

router = APIRouter(prefix="/google-auth", tags=["google-auth"])

from urllib.parse import urlencode

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive"
]

def get_google_client_credentials(db: Session):
    """
    Retorna (client_id, client_secret) desde los ajustes del sistema o variables de entorno.
    """
    client_id_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_client_id").first()
    client_secret_setting = db.query(SystemSetting).filter(SystemSetting.key == "google_client_secret").first()
    
    client_id = client_id_setting.value if client_id_setting else os.getenv("GOOGLE_CLIENT_ID")
    client_secret = client_secret_setting.value if client_secret_setting else os.getenv("GOOGLE_CLIENT_SECRET")
    
    return client_id, client_secret

import os

@router.get("/authorize")
def authorize_google(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Genera la URL de autorización para el flujo de Google OAuth2.
    """
    client_id, client_secret = get_google_client_credentials(db)
    
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Las credenciales de Google OAuth (Client ID y Client Secret) no están configuradas en los Ajustes del Sistema."
        )
        
    # Usar el backend de Railway directamente para recibir el callback
    redirect_uri = "https://ancla-crm-backend-production.up.railway.app/api/v1/google-auth/callback"
    if os.getenv("IS_LOCAL"):
        redirect_uri = "http://localhost:8001/api/v1/google-auth/callback"
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": str(current_user.id),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true"
    }
    
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    
    return {"url": auth_url, "authorization_url": auth_url}


@router.get("/callback")
async def google_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="User ID representing the advisor"),
    db: Session = Depends(get_db)
) -> Any:
    """
    Callback de Google OAuth que intercambia el código de autorización por tokens de acceso/refresco.
    """
    production_domain = os.getenv("PRODUCTION_DOMAIN", "https://anclaspecialprojects.com")
    frontend_base = production_domain if "anclaspecialprojects" in production_domain or not os.getenv("IS_LOCAL") else "http://localhost:5174"

    user_id = int(state)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url=f"{frontend_base}/settings?google_auth=error&error_msg=UserNotFound")
        
    client_id, client_secret = get_google_client_credentials(db)
    if not client_id or not client_secret:
        return RedirectResponse(url=f"{frontend_base}/settings?google_auth=error&error_msg=CredentialsNotConfigured")
        
    token_url = "https://oauth2.googleapis.com/token"
    
    # Intentar con el redirect_uri de Railway primero, luego con el de producción si falla
    redirect_uris_to_try = [
        "https://ancla-crm-backend-production.up.railway.app/api/v1/google-auth/callback",
        f"{production_domain}/api/v1/google-auth/callback"
    ]
    
    success = False
    last_error = ""
    
    for r_uri in redirect_uris_to_try:
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": r_uri,
            "grant_type": "authorization_code"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, data=payload)
                if response.status_code == 200:
                    token_data = response.json()
                    access_token = token_data.get("access_token")
                    refresh_token = token_data.get("refresh_token")
                    expires_in = token_data.get("expires_in", 3600)
                    
                    user.google_access_token = encrypt_value(access_token)
                    if refresh_token:
                        user.google_refresh_token = encrypt_value(refresh_token)
                    user.google_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
                    
                    db.add(user)
                    db.commit()
                    success = True
                    logger.info(f"Asesor {user.full_name} conectado exitosamente a Google OAuth2.")
                    break
                else:
                    last_error = response.text
        except Exception as e:
            last_error = str(e)
            
    if not success:
        logger.error(f"Fallo en callback de Google OAuth: {last_error}")
        return RedirectResponse(url=f"{frontend_base}/settings?google_auth=error&error_msg=TokenExchangeFailed")
        
    return RedirectResponse(url=f"{frontend_base}/settings?google_auth=success")


@router.get("/exchange-code")
async def exchange_google_code(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="User ID"),
    db: Session = Depends(get_db)
) -> Any:
    """
    Endpoint JSON para intercambiar código de Google desde el frontend SPA.
    """
    production_domain = os.getenv("PRODUCTION_DOMAIN", "https://anclaspecialprojects.com")
    user_id = int(state)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"status": "error", "message": "Usuario no encontrado"}

    client_id, client_secret = get_google_client_credentials(db)
    if not client_id or not client_secret:
        return {"status": "error", "message": "Credenciales de Google no configuradas"}

    token_url = "https://oauth2.googleapis.com/token"
    redirect_uris_to_try = [
        f"{production_domain}/api/v1/google-auth/callback",
        "https://ancla-crm-backend-production.up.railway.app/api/v1/google-auth/callback"
    ]

    for r_uri in redirect_uris_to_try:
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": r_uri,
            "grant_type": "authorization_code"
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(token_url, data=payload)
                if response.status_code == 200:
                    token_data = response.json()
                    access_token = token_data.get("access_token")
                    refresh_token = token_data.get("refresh_token")
                    expires_in = token_data.get("expires_in", 3600)

                    user.google_access_token = encrypt_value(access_token)
                    if refresh_token:
                        user.google_refresh_token = encrypt_value(refresh_token)
                    user.google_token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

                    db.add(user)
                    db.commit()
                    return {"status": "success", "message": "Conectado exitosamente con Google"}
        except Exception as e:
            logger.error(f"Error: {e}")

    return {"status": "error", "message": "No se pudo intercambiar el código"}



@router.get("/status")
def google_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Retorna el estado de la conexión de Google OAuth para el asesor logueado.
    """
    is_connected = current_user.google_refresh_token is not None
    has_access = current_user.google_access_token is not None
    
    return {
        "connected": is_connected,
        "has_access_token": has_access,
        "expiry": current_user.google_token_expiry.isoformat() if current_user.google_token_expiry else None
    }


@router.post("/disconnect")
def google_disconnect(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Desconecta la cuenta de Google del asesor logueado eliminando sus tokens.
    """
    current_user.google_access_token = None
    current_user.google_refresh_token = None
    current_user.google_token_expiry = None
    
    db.add(current_user)
    db.commit()
    
    return {"status": "success", "message": "Cuenta de Google desconectada exitosamente."}
