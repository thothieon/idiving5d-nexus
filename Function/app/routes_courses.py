# app/routes_courses.py  ── idiving5d-OctoFlow v260310
# ============================================================
# 課程開課排程 API
#
# Public  (無需驗證):
#   GET  /api/courses/schedules          官網讀取開課日期
#
# Admin   (需 X-Admin-Token):
#   GET    /admin/api/courses/schedules  管理後台列表
#   POST   /admin/api/courses/schedules  新增排程
#   PUT    /admin/api/courses/schedules/{id}  修改排程
#   DELETE /admin/api/courses/schedules/{id}  刪除排程
#
# main.py 加上：
#   from app.routes_courses import public_router as courses_public_router
#   from app.routes_courses import admin_router  as courses_admin_router
#   app.include_router(courses_public_router, prefix="/api")
#   app.include_router(courses_admin_router,  prefix="/admin/api")
# ============================================================
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.db import get_conn
from app.auth_staff import get_current_staff, require_admin_staff

public_router = APIRouter()
admin_router  = APIRouter()


# ── Pydantic Models ──────────────────────────────────────────

class CourseScheduleCreate(BaseModel):
    course_code: str = Field(..., max_length=20)
    course_name: str = Field(..., max_length=100)
    start_date:  str   # YYYY-MM-DD
    end_date:    str   # YYYY-MM-DD
    color:       str   = Field('#1e90ff', max_length=10)
    note:        Optional[str] = Field(None, max_length=255)
    is_active:   int   = 1


class CourseScheduleUpdate(BaseModel):
    course_code: Optional[str] = Field(None, max_length=20)
    course_name: Optional[str] = Field(None, max_length=100)
    start_date:  Optional[str] = None
    end_date:    Optional[str] = None
    color:       Optional[str] = Field(None, max_length=10)
    note:        Optional[str] = Field(None, max_length=255)
    is_active:   Optional[int] = None


# ── Public Endpoint ──────────────────────────────────────────

# 官網讀取：回傳所有啟用中的排程（依開課日排序）
@public_router.get("/courses/schedules")
async def public_list_schedules():
    """官網取得所有啟用的課程排程，不需要驗證"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, course_code, course_name,
                       DATE_FORMAT(start_date,'%Y-%m-%d') AS start_date,
                       DATE_FORMAT(end_date,  '%Y-%m-%d') AS end_date,
                       color, note
                FROM course_schedules
                WHERE is_active = 1
                ORDER BY start_date ASC
                """
            )
            rows = await cur.fetchall()
    return {"ok": True, "items": rows}


# ── Admin Endpoints ───────────────────────────────────────────

# 管理後台列表（含停用）
@admin_router.get("/courses/schedules")
async def admin_list_schedules(staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, course_code, course_name,
                       DATE_FORMAT(start_date,'%Y-%m-%d') AS start_date,
                       DATE_FORMAT(end_date,  '%Y-%m-%d') AS end_date,
                       color, note, is_active, created_at, updated_at
                FROM course_schedules
                ORDER BY start_date ASC
                """
            )
            rows = await cur.fetchall()
    return {"ok": True, "items": rows}


# 新增排程（admin only）
@admin_router.post("/courses/schedules")
async def admin_create_schedule(
    body: CourseScheduleCreate,
    staff: dict = Depends(get_current_staff),
):
    require_admin_staff(staff)
    async with get_conn() as conn:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO course_schedules
                      (course_code, course_name, start_date, end_date, color, note, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        body.course_code, body.course_name,
                        body.start_date,  body.end_date,
                        body.color, body.note, body.is_active,
                    ),
                )
                new_id = cur.lastrowid
            await conn.commit()
        except Exception as e:
            await conn.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "id": new_id}


# 修改排程（admin only）
@admin_router.put("/courses/schedules/{schedule_id}")
async def admin_update_schedule(
    schedule_id: int,
    body: CourseScheduleUpdate,
    staff: dict = Depends(get_current_staff),
):
    require_admin_staff(staff)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")

    set_clause = ", ".join(f"{k}=%s" for k in fields)
    values = list(fields.values()) + [schedule_id]

    async with get_conn() as conn:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"UPDATE course_schedules SET {set_clause} WHERE id=%s",
                    values,
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="not found")
            await conn.commit()
        except HTTPException:
            raise
        except Exception as e:
            await conn.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


# 刪除排程（admin only）
@admin_router.delete("/courses/schedules/{schedule_id}")
async def admin_delete_schedule(
    schedule_id: int,
    staff: dict = Depends(get_current_staff),
):
    require_admin_staff(staff)
    async with get_conn() as conn:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM course_schedules WHERE id=%s", (schedule_id,)
                )
                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="not found")
            await conn.commit()
        except HTTPException:
            raise
        except Exception as e:
            await conn.rollback()
            raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}
