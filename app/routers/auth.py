import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.base import User, UserRole
from app.schemas.user import Token, UserResponse, UserCreate
from app.core import security
from app.core.deps import get_current_user, get_current_active_admin

logger = logging.getLogger("auth_router")
router = APIRouter(prefix="/auth", tags=["auth"])

# Protección Anti-Fuerza Bruta en Memoria
_failed_login_attempts: Dict[str, List[datetime]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 60

def _check_rate_limit(client_ip: str, username: str):
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=LOCKOUT_WINDOW_SECONDS)
    
    # Limpiar y contar intentos de IP
    attempts = [t for t in _failed_login_attempts.get(client_ip, []) if t > window_start]
    _failed_login_attempts[client_ip] = attempts
    
    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        logger.warning(f"Intento de fuerza bruta bloqueado desde IP {client_ip} para usuario '{username}'")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos de inicio de sesión. Por favor espera 1 minuto antes de reintentar."
        )

def _record_failed_attempt(client_ip: str):
    now = datetime.utcnow()
    if client_ip not in _failed_login_attempts:
        _failed_login_attempts[client_ip] = []
    _failed_login_attempts[client_ip].append(now)

def _clear_failed_attempts(client_ip: str):
    _failed_login_attempts.pop(client_ip, None)

@router.post("/login", response_model=Token)
def login_access_token(
    request: Request,
    db: Session = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """
    OAuth2 compatible token login, con protección anti-fuerza bruta y rate limiting.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip, form_data.username)

    try:
        login_str = form_data.username.strip()
        login_lower = login_str.lower()
        login_clean = login_lower.replace(" ", "")

        # 1. Coincidencia flexible por email, prefijo, nombre completo o alias sin espacios
        candidate_users = db.query(User).filter(
            (User.email.ilike(login_str)) | 
            (User.email.ilike(f"{login_str}@%")) |
            (User.email.ilike(f"{login_clean}@%")) |
            (User.full_name.ilike(login_str)) |
            (User.full_name.ilike(f"%{login_str}%"))
        ).all()

        # 2. Búsqueda inteligente por fragmento para nombres de usuario flexibles (ej. Lider Liliana)
        if not candidate_users and ("liliana" in login_lower or "lider" in login_lower):
            candidate_users = db.query(User).filter(
                (User.email.ilike("%liliana%")) |
                (User.full_name.ilike("%liliana%"))
            ).all()

        user = None
        for u in candidate_users:
            if u.is_active and security.verify_password(form_data.password, u.hashed_password):
                user = u
                break

        if not user:
            _record_failed_attempt(client_ip)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Usuario o contraseña incorrectos",
            )
        
        # Login exitoso: limpiar historial de fallos
        _clear_failed_attempts(client_ip)

        access_token_expires = timedelta(minutes=security.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        return {
            "access_token": security.create_access_token(
                user.id, expires_delta=access_token_expires
            ),
            "token_type": "bearer",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error durante autenticación: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor al procesar el inicio de sesión."
        )

@router.get("/me")
def read_user_me(
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Get current user profile con rol normalizado a 'admin' o 'asesor'.
    """
    role_raw = str(current_user.role.value if hasattr(current_user.role, 'value') else current_user.role).lower()
    clean_role = "admin" if "admin" in role_raw else "asesor"
    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": clean_role,
        "is_active": current_user.is_active,
        "avatar_url": current_user.avatar_url
    }

@router.get("/users")
def get_all_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Recupera la lista de todos los usuarios registrados con su conteo de prospectos asignados.
    """
    from app.models.base import Contact
    from sqlalchemy import func

    users = db.query(User).order_by(User.id.asc()).all()
    
    # Subconsulta para contar leads asignados por usuario
    lead_counts = db.query(
        Contact.assigned_user_id,
        func.count(Contact.id).label("count")
    ).filter(Contact.assigned_user_id.isnot(None)).group_by(Contact.assigned_user_id).all()
    count_map = {row[0]: row[1] for row in lead_counts}

    results = []
    for u in users:
        results.append({
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role.value if hasattr(u.role, "value") else str(u.role),
            "is_active": u.is_active,
            "avatar_url": u.avatar_url,
            "assigned_leads_count": count_map.get(u.id, 0),
            "created_at": u.created_at.isoformat() if u.created_at else None
        })
    return results

@router.put("/users/{user_id}")
def update_user_by_admin(
    user_id: int,
    user_in: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_admin)
) -> Any:
    """
    Actualiza datos de un usuario (Solo Administradores).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    if "full_name" in user_in and user_in["full_name"]:
        user.full_name = user_in["full_name"]
    if "email" in user_in and user_in["email"]:
        user.email = user_in["email"].lower().strip()
    if "role" in user_in and user_in["role"]:
        user.role = UserRole(user_in["role"])
    if "is_active" in user_in:
        user.is_active = bool(user_in["is_active"])
    if "password" in user_in and user_in["password"]:
        user.hashed_password = security.get_password_hash(user_in["password"])

    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role.value if hasattr(user.role, "value") else str(user.role),
        "is_active": user.is_active
    }

@router.post("/register", response_model=UserResponse)
def register_user(
    *,
    db: Session = Depends(get_db),
    user_in: UserCreate,
    current_user: User = Depends(get_current_active_admin) # Solo administradores pueden crear nuevos usuarios
) -> Any:
    """
    Create new user (Admins only).
    """
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=400,
            detail="El email ya está registrado en el sistema.",
        )
    
    db_obj = User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=user_in.role,
        is_active=user_in.is_active
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj

@router.post("/setup-initial-admin", response_model=UserResponse)
def setup_initial_admin(
    *,
    db: Session = Depends(get_db),
    user_in: UserCreate
) -> Any:
    """
    Crea el primer administrador en el sistema si no hay usuarios registrados.
    """
    user_exists = db.query(User).first()
    if user_exists:
        raise HTTPException(
            status_code=400,
            detail="El sistema ya ha sido inicializado. Usa /register para crear más usuarios.",
        )
    
    db_obj = User(
        email=user_in.email,
        hashed_password=security.get_password_hash(user_in.password),
        full_name=user_in.full_name,
        role=UserRole.ADMIN,  # Siempre admin
        is_active=True
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return db_obj


import uuid
from datetime import datetime, timedelta
from app.models.base import UserInvitation
from app.schemas.user import InvitationCreate, InvitationResponse, InvitedRegister

@router.post("/invitations", response_model=InvitationResponse)
def create_invitation(
    *,
    db: Session = Depends(get_db),
    inv_in: InvitationCreate,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Genera un token de invitación seguro para registrar a un nuevo usuario (Solo Admin).
    """
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos de administrador para invitar usuarios."
        )

    # Si ya hay un usuario con ese correo o una invitación activa no usada, advertir
    existing_user = db.query(User).filter(User.email == inv_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario registrado con este correo electrónico."
        )

    # Eliminar invitaciones anteriores no usadas para este mismo email
    db.query(UserInvitation).filter(UserInvitation.email == inv_in.email, UserInvitation.is_used == False).delete()

    token = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=24)

    db_inv = UserInvitation(
        email=inv_in.email,
        role=inv_in.role,
        token=token,
        expires_at=expires_at,
        is_used=False
    )
    db.add(db_inv)
    db.commit()
    db.refresh(db_inv)
    return db_inv


@router.get("/invitations/validate", response_model=InvitationResponse)
def validate_invitation(
    *,
    db: Session = Depends(get_db),
    token: str
) -> Any:
    """
    Valida si un token de invitación es válido, no ha expirado y no ha sido utilizado.
    """
    inv = db.query(UserInvitation).filter(UserInvitation.token == token).first()
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token de invitación inválido o inexistente."
        )
    if inv.is_used:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta invitación ya ha sido utilizada."
        )
    if inv.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La invitación ha expirado (validez de 24 horas)."
        )
    return inv


@router.post("/register-invited", response_model=UserResponse)
def register_invited_user(
    *,
    db: Session = Depends(get_db),
    reg_in: InvitedRegister
) -> Any:
    """
    Registra una cuenta de usuario a partir de un token de invitación válido.
    """
    inv = db.query(UserInvitation).filter(UserInvitation.token == reg_in.token).first()
    if not inv or inv.is_used or inv.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitación inválida, expirada o previamente usada."
        )

    # Crear el usuario en la base de datos
    db_user = User(
        email=inv.email,
        hashed_password=security.get_password_hash(reg_in.password),
        full_name=reg_in.full_name,
        role=inv.role,
        is_active=True
    )
    db.add(db_user)
    
    # Marcar invitación como usada
    inv.is_used = True
    db.add(inv)
    
    db.commit()
    db.refresh(db_user)
    
    return db_user

