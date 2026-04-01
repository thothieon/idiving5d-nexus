# app/routes_tags.py  ── 客戶標籤管理
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.db import get_conn
from app.auth_staff import get_current_staff, require_admin_staff

router = APIRouter()


class TagCreate(BaseModel):
    name:  str
    color: str = "#6B7280"


class TagSetBody(BaseModel):
    tag_ids: list[int]


# ── 標籤清單（所有客服）──────────────────────────────────────
@router.get("/tags")
async def list_tags(staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, color, created_at FROM tags ORDER BY name"
            )
            rows = await cur.fetchall()
    return {"ok": True, "items": rows}


# ── 建立標籤（admin only）───────────────────────────────────
@router.post("/tags")
async def create_tag(body: TagCreate, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    name  = (body.name  or "").strip()
    color = (body.color or "#6B7280").strip()
    if not name:
        raise HTTPException(status_code=400, detail="標籤名稱不能為空")
    if not (color.startswith("#") and len(color) == 7):
        raise HTTPException(status_code=400, detail="顏色格式錯誤（需 #RRGGBB）")
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    "INSERT INTO tags (name, color) VALUES (%s, %s)",
                    (name, color),
                )
                tag_id = cur.lastrowid
            except Exception:
                raise HTTPException(status_code=409, detail="標籤名稱已存在")
        await conn.commit()
    return {"ok": True, "id": tag_id}


# ── 刪除標籤（admin only）───────────────────────────────────
@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM customer_tag_map WHERE tag_id=%s", (tag_id,)
            )
            await cur.execute("DELETE FROM tags WHERE id=%s", (tag_id,))
        await conn.commit()
    return {"ok": True}


# ── 取得某客戶的標籤（所有客服）────────────────────────────
@router.get("/customers/{customer_id}/tags")
async def get_customer_tags(
    customer_id: int,
    staff: dict = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT t.id, t.name, t.color
                FROM customer_tag_map ctm
                JOIN tags t ON ctm.tag_id = t.id
                WHERE ctm.customer_id = %s
                ORDER BY t.name
                """,
                (customer_id,),
            )
            rows = await cur.fetchall()
    return {"ok": True, "items": rows}


# ── 設定某客戶的標籤（全量替換，所有客服）──────────────────
@router.put("/customers/{customer_id}/tags")
async def set_customer_tags(
    customer_id: int,
    body: TagSetBody,
    staff: dict = Depends(get_current_staff),
):
    staff_id = staff.get("id")
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM customer_tag_map WHERE customer_id=%s", (customer_id,)
            )
            if body.tag_ids:
                await cur.executemany(
                    "INSERT IGNORE INTO customer_tag_map (customer_id, tag_id, assigned_by)"
                    " VALUES (%s, %s, %s)",
                    [(customer_id, tid, staff_id) for tid in body.tag_ids],
                )
        await conn.commit()
    return {"ok": True}
