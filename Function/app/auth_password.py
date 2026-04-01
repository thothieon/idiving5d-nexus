# app/auth_password.py  ── idiving5d-OctoFlow
import bcrypt


def hash_password(plain: str) -> str:
    """將明文密碼 bcrypt hash 後回傳字串"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """驗證明文密碼是否符合 bcrypt hash"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False
