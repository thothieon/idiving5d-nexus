# app/routes_rag.py  ── 知識庫管理 API
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import get_conn
from app.auth_staff import get_current_staff
from app.rag_retriever import get_embedding

router = APIRouter()

VALID_CATEGORIES = {"faq", "course", "policy", "general"}


# ── Pydantic ──────────────────────────────────────────────────

class ChunkCreate(BaseModel):
    category: str        = "faq"
    title:    str        = Field(..., max_length=200)
    content:  str        = Field(..., min_length=1)
    is_active: int       = 1

class ChunkUpdate(BaseModel):
    category:  Optional[str] = None
    title:     Optional[str] = Field(None, max_length=200)
    content:   Optional[str] = None
    is_active: Optional[int] = None


# ── 列表 ──────────────────────────────────────────────────────

@router.get("/rag/chunks")
async def list_chunks(
    category: Optional[str] = None,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            if category:
                await cur.execute(
                    "SELECT id, category, title, content, is_active, "
                    "embedding IS NOT NULL AS has_embedding, created_at, updated_at "
                    "FROM knowledge_chunks WHERE category=%s ORDER BY category, title",
                    (category,),
                )
            else:
                await cur.execute(
                    "SELECT id, category, title, content, is_active, "
                    "embedding IS NOT NULL AS has_embedding, created_at, updated_at "
                    "FROM knowledge_chunks ORDER BY category, title"
                )
            rows = await cur.fetchall()
    return {"items": [dict(r) for r in rows]}


# ── 建立 ──────────────────────────────────────────────────────

@router.post("/rag/chunks")
async def create_chunk(
    body: ChunkCreate,
    staff = Depends(get_current_staff),
):
    if body.category not in VALID_CATEGORIES:
        raise HTTPException(400, f"category 必須是 {VALID_CATEGORIES} 之一")

    # 產生 embedding
    emb = await get_embedding(f"{body.title}\n{body.content}")
    emb_json = json.dumps(emb) if emb else None

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO knowledge_chunks (category, title, content, embedding, is_active) "
                "VALUES (%s, %s, %s, %s, %s)",
                (body.category, body.title, body.content, emb_json, body.is_active),
            )
            new_id = cur.lastrowid
        await conn.commit()

    return {"ok": True, "id": new_id, "embedded": emb is not None}


# ── 更新 ──────────────────────────────────────────────────────

@router.patch("/rag/chunks/{chunk_id}")
async def update_chunk(
    chunk_id: int,
    body: ChunkUpdate,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, title, content FROM knowledge_chunks WHERE id=%s", (chunk_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(404, "找不到此知識片段")

            data = body.model_dump(exclude_unset=True)
            if "category" in data and data["category"] not in VALID_CATEGORIES:
                raise HTTPException(400, f"category 必須是 {VALID_CATEGORIES} 之一")

            # 內容有變更 → 重新 embed
            content_changed = "title" in data or "content" in data
            if content_changed:
                new_title   = data.get("title",   row["title"])
                new_content = data.get("content", row["content"])
                emb = await get_embedding(f"{new_title}\n{new_content}")
                data["embedding"] = json.dumps(emb) if emb else None

            updates, params = [], []
            for field, val in data.items():
                updates.append(f"{field}=%s")
                params.append(val)

            if not updates:
                raise HTTPException(400, "沒有要更新的欄位")

            params.append(chunk_id)
            await cur.execute(
                f"UPDATE knowledge_chunks SET {', '.join(updates)}, updated_at=NOW() WHERE id=%s",
                params,
            )
        await conn.commit()
    return {"ok": True}


# ── 刪除 ──────────────────────────────────────────────────────

@router.delete("/rag/chunks/{chunk_id}")
async def delete_chunk(
    chunk_id: int,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM knowledge_chunks WHERE id=%s", (chunk_id,))
        await conn.commit()
    return {"ok": True}


# ── 重新 Embed 全部 ───────────────────────────────────────────

@router.post("/rag/chunks/reembed-all")
async def reembed_all(staff = Depends(get_current_staff)):
    """將所有知識片段重新生成 embedding（更換 model 後使用）"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, title, content FROM knowledge_chunks WHERE is_active=1")
            rows = await cur.fetchall()

        count = 0
        for row in rows:
            emb = await get_embedding(f"{row['title']}\n{row['content']}")
            if emb:
                async with conn.cursor() as cur2:
                    await cur2.execute(
                        "UPDATE knowledge_chunks SET embedding=%s, updated_at=NOW() WHERE id=%s",
                        (json.dumps(emb), row["id"]),
                    )
                count += 1

        await conn.commit()
    return {"ok": True, "updated": count}
