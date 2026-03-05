# app/auth_staff.py  ── Line@v260306
import os
from fastapi import Header, HTTPException

from app.db import get_conn
from app.security_staff_tokens import sha256_hex


async def _touch_token_last_used(conn, token_id: int):
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE staff_tokens SET last_used_at=NOW() WHERE id=%s", (token_id,)
            )
        await conn.commit()
    except Exception:
        await conn.rollback()


async def _load_staff_by_token(raw_token: str):
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

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, (token_hash,))
            row = await cur.fetchone()
        if row:
            await _touch_token_last_used(conn, int(row["token_id"]))
        return row


async def get_current_staff(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
):
    token = (x_admin_token or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="missing X-Admin-Token")

    row = await _load_staff_by_token(token)
    if not row:
        raise HTTPException(status_code=401, detail="invalid/expired token")
    return row


def require_admin_staff(staff: dict):
    """同步檢查即可，不需要 DB 操作"""
    if (staff.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return staff
