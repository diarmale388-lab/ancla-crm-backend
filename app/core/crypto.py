import base64
import hashlib
import hmac
import os
import secrets
from typing import Optional
from app.config import settings

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

def _get_derived_key() -> bytes:
    secret = getattr(settings, "ENCRYPTION_KEY", None) or settings.SECRET_KEY
    return hashlib.sha256(secret.encode('utf-8')).digest()

def _fallback_encrypt(plain_text: str) -> str:
    key = _get_derived_key()
    iv = secrets.token_bytes(16)
    data = plain_text.encode('utf-8')
    # Generar keystream usando HMAC-SHA256
    keystream = bytearray()
    counter = 0
    while len(keystream) < len(data):
        counter_bytes = counter.to_bytes(4, 'big')
        keystream.extend(hmac.new(key, iv + counter_bytes, hashlib.sha256).digest())
        counter += 1
    cipher_bytes = bytes(d ^ k for d, k in zip(data, keystream[:len(data)]))
    tag = hmac.new(key, iv + cipher_bytes, hashlib.sha256).digest()[:16]
    payload = iv + tag + cipher_bytes
    return f"enc:v1:{base64.urlsafe_b64encode(payload).decode('utf-8')}"

def _fallback_decrypt(cipher_b64: str) -> Optional[str]:
    try:
        raw = base64.urlsafe_b64decode(cipher_b64.encode('utf-8'))
        if len(raw) < 32:
            return None
        key = _get_derived_key()
        iv = raw[:16]
        expected_tag = raw[16:32]
        cipher_bytes = raw[32:]
        computed_tag = hmac.new(key, iv + cipher_bytes, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(expected_tag, computed_tag):
            return None
        keystream = bytearray()
        counter = 0
        while len(keystream) < len(cipher_bytes):
            counter_bytes = counter.to_bytes(4, 'big')
            keystream.extend(hmac.new(key, iv + counter_bytes, hashlib.sha256).digest())
            counter += 1
        plain_bytes = bytes(c ^ k for c, k in zip(cipher_bytes, keystream[:len(cipher_bytes)]))
        return plain_bytes.decode('utf-8')
    except Exception:
        return None

def encrypt_value(plain_text: Optional[str]) -> Optional[str]:
    """
    Cifra un valor de texto usando AES-256 (Fernet) o HMAC-SHA256 Authenticated Stream Cipher.
    Si el valor está vacío o ya está cifrado con prefijo 'enc:v1:' o 'enc::', lo maneja limpiamente.
    """
    if not plain_text:
        return plain_text
    if plain_text.startswith("enc::") or plain_text.startswith("enc:v1:"):
        return plain_text  # Ya cifrado

    if HAS_CRYPTOGRAPHY:
        try:
            f = Fernet(base64.urlsafe_b64encode(_get_derived_key()))
            encrypted_bytes = f.encrypt(plain_text.encode('utf-8'))
            return f"enc:v1:{encrypted_bytes.decode('utf-8')}"
        except Exception:
            pass

    return _fallback_encrypt(plain_text)

def decrypt_value(encrypted_text: Optional[str]) -> Optional[str]:
    """
    Descifra un valor cifrado con 'enc:v1:' o 'enc::'. Si no tiene prefijo, retorna el texto plano original.
    """
    if not encrypted_text:
        return encrypted_text
    
    raw_cipher_str = None
    if encrypted_text.startswith("enc:v1:"):
        raw_cipher_str = encrypted_text[7:]
    elif encrypted_text.startswith("enc::"):
        raw_cipher_str = encrypted_text[5:]
    else:
        return encrypted_text  # Es texto plano preexistente (retrocompatibilidad)

    if HAS_CRYPTOGRAPHY:
        try:
            f = Fernet(base64.urlsafe_b64encode(_get_derived_key()))
            raw_cipher = raw_cipher_str.encode('utf-8')
            decrypted_bytes = f.decrypt(raw_cipher)
            return decrypted_bytes.decode('utf-8')
        except Exception:
            pass

    dec = _fallback_decrypt(raw_cipher_str)
    return dec if dec is not None else encrypted_text


# Alias para claridad semántica
encrypt_secret = encrypt_value
decrypt_secret = decrypt_value

def mask_secret(secret_val: Optional[str], visible_chars: int = 4) -> str:
    """
    Enmascara un secreto para mostrarlo de forma segura en respuestas JSON (ej. '••••••••••••4x8F').
    """
    if not secret_val:
        return ""
    decrypted = decrypt_value(secret_val)
    if not decrypted or len(decrypted) <= visible_chars:
        return "••••••••"
    return f"{'•' * 12}{decrypted[-visible_chars:]}"
