# app/auth_staff.py  ── idiving5d-OctoFlow v260310
import json
import os
from fastapi import Header, HTTPException

from app.db import get_conn
from app.security_staff_tokens import sha256_hex


# 更新指定 token 的最後使用時間（last_used_at）
async def _touch_token_last_used(conn, token_id: int):
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE staff_tokens SET last_used_at=NOW() WHERE id=%s", (token_id,)
            )
        await conn.commit()
    except Exception:
        await conn.rollback()


# 依據原始 token 查詢對應的有效員工資料，並更新最後使用時間
async def _load_staff_by_token(raw_token: str):
    token_hash = sha256_hex(raw_token)

    sql = """
      SELECT
        st.id AS token_id,
        st.staff_id,
        s.name,
        s.email,
        s.role,
        s.permissions,
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
            # permissions 欄位可能是 JSON 字串，解析成 dict
            if isinstance(row.get("permissions"), str):
                try:
                    row["permissions"] = json.loads(row["permissions"])
                except Exception:
                    row["permissions"] = None
        return row


# FastAPI Depends 注入函式：從請求標頭 X-Admin-Token 驗證員工身份
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


# 檢查員工是否具有 admin 角色，不符合則拋出 403 錯誤
def require_admin_staff(staff: dict):
    """同步檢查即可，不需要 DB 操作"""
    if (staff.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="admin only")
    return staff
