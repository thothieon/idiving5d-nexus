# auth_staff.py
import os
import pymysql
from fastapi import Header, HTTPException

from app.security_staff_tokens import sha256_hex

DB_HOST = os.environ.get("DB_HOST", "192.168.12.159")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "rootpwd")
DB_NAME = os.environ.get("DB_NAME", "iDiving_LineTest")


def get_conn():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def _touch_token_last_used(conn, token_id: int):
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE staff_tokens SET last_used_at=NOW() WHERE id=%s", (token_id,))
        conn.commit()
    except Exception:
        conn.rollback()


def _load_staff_by_token(raw_token: str):
    token_hash = sha256_hex(raw_token)

    sql = """
      SELECT
        st.id AS token_id,
        st.staff_id,
        s.name,
        s.role,
        s.line_user_id,
        s.picture_url,
        s.is_active
      FROM staff_tokens st
      JOIN staff s ON s.id = st.staff_id
      WHERE st.token_hash=%s
        AND st.revoked_at IS NULL
        AND s.is_active=1
      LIMIT 1
    """

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (token_hash,))
            row = cur.fetchone()
        if row:
            _touch_token_last_used(conn, int(row["token_id"]))
        return row
    finally:
        conn.close()


def get_current_staff(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    token = (x_admin_token or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing X-Admin-Token")

    row = _load_staff_by_token(token)
    if not row:
        raise HTTPException(status_code=401, detail="invalid/expired token")
    return row


def require_admin_staff(staff: dict):
    if (staff.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return staff
