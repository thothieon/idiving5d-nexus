# app/routes_quickreply.py  ── Line@v260306
# ============================================================
# Quick Reply 規則後台管理 API
# main.py 加上：
#   from app.routes_quickreply import router as quickreply_router
#   app.include_router(quickreply_router, prefix="/admin/api")
# ============================================================
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List

from app.db import get_conn
from app.auth_staff import get_current_staff, require_admin_staff

router = APIRouter()


# ── Pydantic Models ──────────────────────────────────────────

class QuickReplyButton(BaseModel):
    label: str      # 按鈕顯示文字，最多 20 字
    url:   str      # 點下去開啟的 URL


class QuickReplyRuleCreate(BaseModel):
    keyword:    str
    reply_text: str
    buttons:    List[QuickReplyButton]
    is_active:  bool = True


class QuickReplyRuleUpdate(BaseModel):
    keyword:    str | None = None
    reply_text: str | None = None
    buttons:    List[QuickReplyButton] | None = None
    is_active:  bool | None = None


# ── Endpoints ────────────────────────────────────────────────

@router.get("/quickreply/rules")
async def list_rules(staff: dict = Depends(get_current_staff)):
    """列出所有 Quick Reply 規則"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, keyword, reply_text, buttons, is_active, created_at, updated_at "
                "FROM quick_reply_rules ORDER BY id ASC"
            )
            rows = await cur.fetchall()
        # buttons 是 JSON 字串，parse 成 list 給前端
        for r in rows:
            if isinstance(r["buttons"], str):
                r["buttons"] = json.loads(r["buttons"])
        return {"ok": True, "items": rows}


@router.post("/quickreply/rules")
async def create_rule(
    body: QuickReplyRuleCreate,
    staff: dict = Depends(get_current_staff),
):
    """新增一條 Quick Reply 規則（admin only）"""
    require_admin_staff(staff)

    keyword = (body.keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 不能為空")
    if not body.buttons:
        raise HTTPException(status_code=400, detail="至少要有一個按鈕")
    if len(body.buttons) > 13:
        raise HTTPException(status_code=400, detail="LINE Quick Reply 最多 13 個按鈕")

    buttons_json = json.dumps(
        [{"label": b.label, "url": b.url} for b in body.buttons],
        ensure_ascii=False
    )

    async with get_conn() as conn:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO quick_reply_rules
                      (keyword, reply_text, buttons, is_active)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (keyword, body.reply_text, buttons_json, 1 if body.is_active else 0)
                )
                new_id = cur.lastrowid
            await conn.commit()
            return {"ok": True, "id": new_id}
        except Exception as e:
            if "Duplicate" in str(e):
                raise HTTPException(status_code=409, detail=f"關鍵字「{keyword}」已存在")
            raise HTTPException(status_code=500, detail=str(e))


@router.put("/quickreply/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: QuickReplyRuleUpdate,
    staff: dict = Depends(get_current_staff),
):
    """更新 Quick Reply 規則（admin only）"""
    require_admin_staff(staff)

    parts = []
    vals  = []

    if body.keyword is not None:
        parts.append("keyword=%s");    vals.append(body.keyword.strip())
    if body.reply_text is not None:
        parts.append("reply_text=%s"); vals.append(body.reply_text)
    if body.buttons is not None:
        if len(body.buttons) > 13:
            raise HTTPException(status_code=400, detail="LINE Quick Reply 最多 13 個按鈕")
        parts.append("buttons=%s")
        vals.append(json.dumps(
            [{"label": b.label, "url": b.url} for b in body.buttons],
            ensure_ascii=False
        ))
    if body.is_active is not None:
        parts.append("is_active=%s"); vals.append(1 if body.is_active else 0)

    if not parts:
        raise HTTPException(status_code=400, detail="沒有任何欄位要更新")

    vals.append(rule_id)

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE quick_reply_rules SET {', '.join(parts)}, updated_at=NOW() WHERE id=%s",
                vals
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="rule not found")
        await conn.commit()
        return {"ok": True}


@router.delete("/quickreply/rules/{rule_id}")
async def delete_rule(
    rule_id: int,
    staff: dict = Depends(get_current_staff),
):
    """刪除 Quick Reply 規則（admin only）"""
    require_admin_staff(staff)

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM quick_reply_rules WHERE id=%s", (rule_id,)
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="rule not found")
        await conn.commit()
        return {"ok": True}
