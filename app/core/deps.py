from typing import Generator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.base import User, UserRole, Contact
from app.schemas.user import TokenData

# fastapi busca el token en el header Authorization
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

from app.core.security import get_global_panic_revocation_timestamp

def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    revoked_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sesión revocada por motivos de seguridad. Inicie sesión nuevamente.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
        token_tv: int = payload.get("tv", 1)
        token_iat: int = payload.get("iat", 0)
        token_data = TokenData(user_id=user_id)
    except (JWTError, ValueError):
        raise credentials_exception

    # 1. Verificar si hubo revocación global de pánico posterior a la emisión del token
    global_panic_ts = get_global_panic_revocation_timestamp()
    if global_panic_ts > 0 and token_iat <= global_panic_ts:
        raise revoked_exception
        
    target_uid = token_data.user_id
    # Mapeo transparente de compatibilidad hacia los 3 perfiles oficiales definitivos
    if target_uid in [1, 2, 6]:
        target_uid = 5  # Super Administrador (diarmale388)
    elif target_uid in [3, 8]:
        target_uid = 9  # Liliana León
    elif target_uid in [10]:
        target_uid = 4  # Harvey Covaleda

    user = db.query(User).filter(User.id == target_uid).first()
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )
        
    # 2. Verificar versionado individual de sesión (Logout all / Kill Switch por usuario)
    user_tv = getattr(user, "token_version", 1)
    if token_tv < user_tv:
        raise revoked_exception

    return user

def get_current_active_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    role_str = str(getattr(current_user.role, "value", current_user.role)).lower()
    if role_str not in ["admin", "userrole.admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene suficientes privilegios de administrador"
        )
    return current_user

def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Exige rol de Administrador o Dirección Comercial (Liliana León).
    """
    return get_current_active_admin(current_user)

def require_contact_access(
    contact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Contact:
    """
    Verifica que el usuario actual tenga acceso legítimo sobre el contacto (sea Admin o el Asesor Asignado).
    """
    from app.models.base import Contact
    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    
    role_str = str(getattr(current_user.role, "value", current_user.role)).lower()
    if role_str not in ["admin", "userrole.admin"]:
        if contact.assigned_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acceso denegado: No tienes autorización sobre este prospecto."
            )
    return contact

