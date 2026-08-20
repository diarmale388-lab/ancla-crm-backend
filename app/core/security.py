from datetime import datetime, timedelta
from typing import Any, Union
from jose import jwt
from passlib.context import CryptContext
from app.config import settings

import bcrypt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Variable global en memoria para revocación instantánea global de sesiones (Panic Button)
GLOBAL_PANIC_REVOCATION_TIMESTAMP = 0.0

def trigger_global_panic_revocation() -> float:
    global GLOBAL_PANIC_REVOCATION_TIMESTAMP
    import time
    GLOBAL_PANIC_REVOCATION_TIMESTAMP = time.time()
    return GLOBAL_PANIC_REVOCATION_TIMESTAMP

def get_global_panic_revocation_timestamp() -> float:
    return GLOBAL_PANIC_REVOCATION_TIMESTAMP

def create_access_token(
    subject: Union[str, Any], expires_delta: timedelta = None, token_version: int = 1
) -> str:
    import time
    from datetime import timezone
    now_utc = datetime.now(timezone.utc)
    if expires_delta:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {
        "exp": expire,
        "iat": int(time.time()),
        "sub": str(subject),
        "tv": token_version
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])

