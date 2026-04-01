# security_staff_tokens.py
import hashlib
import secrets

TOKEN_PREFIX = "adm_"

# 產生帶有 "adm_" 前綴的隨機管理員 Token
def generate_admin_token() -> str:
    # 32 bytes -> urlsafe 字串，夠用又不會太長
    return TOKEN_PREFIX + secrets.token_urlsafe(32)

# 將字串以 SHA-256 雜湊後回傳十六進位字串（用於 token 儲存）
def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

# 取得 token 的前 8 個字元作為識別前綴（方便管理介面顯示）
def token_prefix(token: str) -> str:
    return token[:8]
