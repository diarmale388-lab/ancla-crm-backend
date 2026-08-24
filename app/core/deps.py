from typing import Generator, Optional
from fastapi import Depends, HTTPException, Query, status
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

# Variante opcional (no lanza 401 automático) usada por get_current_user_flexible,
# que además acepta el token vía query param para recursos embebidos en <img>/<audio>/<a>.
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False
)

from app.core.security import get_global_panic_revocation_timestamp


def _resolve_user_from_token(token: str, db: Session) -> User:
    """
    Decodifica y valida un JWT, y devuelve el usuario activo correspondiente.
    Lanza HTTPException (401/400) si el token o el usuario no son válidos.
    """
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

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Verificar versionado individual de sesión (Logout all / Kill Switch por usuario)
    user_tv = getattr(user, "token_version", 1)
    if token_tv < user_tv:
        raise revoked_exception

    return user


def get_current_user(
    db: Session = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    return _resolve_user_from_token(token, db)


def get_current_user_flexible(
    db: Session = Depends(get_db),
    header_token: Optional[str] = Depends(oauth2_scheme_optional),
    token: Optional[str] = Query(default=None),
) -> User:
    """
    Igual que get_current_user, pero además acepta el JWT como query param (?token=...).
    Uso exclusivo para endpoints que sirven recursos binarios referenciados directamente
    en atributos src/href de HTML (imágenes, audio, PDFs), donde el navegador no puede
    adjuntar el header Authorization. Nunca usar para endpoints JSON normales.
    """
    raw_token = header_token or token
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudieron validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _resolve_user_from_token(raw_token, db)

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

