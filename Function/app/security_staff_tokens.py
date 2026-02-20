# security_staff_tokens.py
import hashlib
import secrets

TOKEN_PREFIX = "adm_"

def generate_admin_token() -> str:
    # 32 bytes -> urlsafe 字串，夠用又不會太長
    return TOKEN_PREFIX + secrets.token_urlsafe(32)

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def token_prefix(token: str) -> str:
    return token[:8]
