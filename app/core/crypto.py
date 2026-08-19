import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from app.config import settings

def _get_fernet_key() -> bytes:
    """
    Deriva una clave Fernet válida de 32 bytes en base64url a partir de settings.SECRET_KEY.
    """
    key_material = settings.SECRET_KEY.encode('utf-8')
    digest = hashlib.sha256(key_material).digest()
    return base64.urlsafe_b64encode(digest)

def encrypt_value(plain_text: Optional[str]) -> Optional[str]:
    """
    Cifra un valor de texto usando AES-256 (Fernet).
    Si el valor está vacío o ya está cifrado con prefijo 'enc::', lo maneja limpiamente.
    """
    if not plain_text:
        return plain_text
    if plain_text.startswith("enc::"):
        return plain_text  # Ya cifrado
    try:
        f = Fernet(_get_fernet_key())
        encrypted_bytes = f.encrypt(plain_text.encode('utf-8'))
        return f"enc::{encrypted_bytes.decode('utf-8')}"
    except Exception:
        return plain_text

def decrypt_value(encrypted_text: Optional[str]) -> Optional[str]:
    """
    Descifra un valor cifrado con 'enc::'. Si no tiene el prefijo, retorna el texto plano original.
    """
    if not encrypted_text:
        return encrypted_text
    if not encrypted_text.startswith("enc::"):
        return encrypted_text  # Es texto plano preexistente (retrocompatibilidad)
    try:
        f = Fernet(_get_fernet_key())
        raw_cipher = encrypted_text[5:].encode('utf-8')
        decrypted_bytes = f.decrypt(raw_cipher)
        return decrypted_bytes.decode('utf-8')
    except Exception:
        # En caso de fallo de descifrado, retornar original seguro
        return encrypted_text
