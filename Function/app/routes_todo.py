# app/routes_todo.py  ── 待處理清單 API
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from app.db import get_conn
from app.auth_staff import get_current_staff

router = APIRouter()


# ── Pydantic ──────────────────────────────────────────────────

class TodoCreate(BaseModel):
    title:       str            = Field(..., max_length=200)
    note:        Optional[str]  = None
    assignee_id: Optional[int]  = None
    due_date:    Optional[str]  = None   # YYYY-MM-DD
    ticket_id:   Optional[int]  = None
    priority:    int            = 1      # 1=一般 2=重要 3=緊急

class TodoUpdate(BaseModel):
    title:       Optional[str]  = Field(None, max_length=200)
    note:        Optional[str]  = None
    assignee_id: Optional[int]  = None
    due_date:    Optional[str]  = None
    ticket_id:   Optional[int]  = None
    priority:    Optional[int]  = None
    is_done:     Optional[int]  = None   # 0 / 1


# ── 列表 ──────────────────────────────────────────────────────

@router.get("/todos")
async def list_todos(
    show_done:  int          = 0,   # 0=只顯示未完成  1=全部
    ticket_id:  Optional[int] = None,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            sql = """
                SELECT t.id, t.title, t.note, t.priority,
                       t.due_date, t.ticket_id, t.is_done, t.done_at,
                       t.created_at, t.updated_at,
                       s_assign.name AS assignee_name,
                       s_create.name AS created_by_name
                FROM todo_items t
                LEFT JOIN staff s_assign ON s_assign.id = t.assignee_id
                LEFT JOIN staff s_create ON s_create.id = t.created_by
            """
            conditions, params = [], []
            if not show_done:
                conditions.append("t.is_done = 0")
            if ticket_id is not None:
                conditions.append("t.ticket_id = %s")
                params.append(ticket_id)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY t.is_done ASC, t.priority DESC, t.due_date ASC, t.created_at ASC"
            await cur.execute(sql, params)
            rows = await cur.fetchall()
    return {"items": [dict(r) for r in rows]}


# ── 建立 ──────────────────────────────────────────────────────

@router.post("/todos")
async def create_todo(
    body: TodoCreate,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """INSERT INTO todo_items
                   (title, note, assignee_id, due_date, ticket_id, priority, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (body.title, body.note, body.assignee_id,
                 body.due_date, body.ticket_id, body.priority, staff["staff_id"])
            )
            new_id = cur.lastrowid
        await conn.commit()
    return {"ok": True, "id": new_id}


# ── 更新 ──────────────────────────────────────────────────────

@router.patch("/todos/{todo_id}")
async def update_todo(
    todo_id: int,
    body: TodoUpdate,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, is_done FROM todo_items WHERE id=%s", (todo_id,))
            row = await cur.fetchone()
            if not row:
                raise HTTPException(404, "找不到此待辦")

            updates, params = [], []
            data = body.model_dump(exclude_unset=True)

            # 切換完成狀態時同步更新 done_at
            if "is_done" in data:
                updates.append("is_done=%s")
                params.append(data.pop("is_done"))
                if params[-1]:
                    updates.append("done_at=NOW()")
                else:
                    updates.append("done_at=NULL")

            for field, val in data.items():
                updates.append(f"{field}=%s")
                params.append(val)

            if not updates:
                raise HTTPException(400, "沒有要更新的欄位")

            updates.append("updated_at=NOW()")
            params.append(todo_id)
            await cur.execute(
                f"UPDATE todo_items SET {', '.join(updates)} WHERE id=%s", params
            )
        await conn.commit()
    return {"ok": True}


# ── 刪除 ──────────────────────────────────────────────────────

@router.delete("/todos/{todo_id}")
async def delete_todo(
    todo_id: int,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM todo_items WHERE id=%s", (todo_id,))
        await conn.commit()
    return {"ok": True}
