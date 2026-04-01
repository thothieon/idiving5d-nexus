# app/routes_ui.py  ── idiving5d-OctoFlow v260310
import os
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from app.auth_staff import get_current_staff
from app.db import get_conn

router = APIRouter()

TEMPLATES_DIR = os.environ.get("TEMPLATES_DIR", "app/templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# 渲染管理後台主頁面（admin_index.html）
@router.get("/admin/ui")
async def admin_ui_index(
    request: Request,
    staff: dict = Depends(get_current_staff),
):
    return templates.TemplateResponse("admin_index.html", {"request": request, "staff": staff})


# 渲染 Turn-Based 客服工作台的總覽頁面（admin_turn_based.html）
@router.get("/admin/uiturn_based")
async def admin_uiturn_index_based(
    request: Request,
    staff: dict = Depends(get_current_staff),
):
    return templates.TemplateResponse("admin_turn_based.html", {"request": request, "staff": staff})


# 渲染指定 ticket 的 Turn-Based 客服對話詳細頁面
@router.get("/admin/uiturn/t/{ticket_id}")
async def admin_uiturn_ticket(
    ticket_id: int,
    request: Request,
    staff: dict = Depends(get_current_staff),
):
    return templates.TemplateResponse(
        "admin_ticket_turn_based.html",
        {"request": request, "ticket_id": ticket_id, "staff": staff},
    )


# 取得管理後台儀表板統計資料（今日新增、服務中、等待中、逾時未回覆的 ticket 數）
@router.get("/admin/api/dashboard")
async def admin_api_dashboard(staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM tickets
                WHERE COALESCE(opened_at, created_at) >= DATE_SUB(NOW(), INTERVAL 1 DAY)
                """
            )
            today_new = (await cur.fetchone())["n"]

            # ✅ 修正：統一使用 current_status（原本混用 status/current_status）
            await cur.execute(
                "SELECT COUNT(*) AS n FROM tickets WHERE current_status='in_progress'"
            )
            open_cnt = (await cur.fetchone())["n"]

            await cur.execute(
                "SELECT COUNT(*) AS n FROM tickets WHERE current_status='waiting'"
            )
            pending_cnt = (await cur.fetchone())["n"]

            await cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM tickets
                WHERE current_status NOT IN ('closed')
                  AND COALESCE(last_customer_message_at, opened_at, created_at)
                      < DATE_SUB(NOW(), INTERVAL 60 MINUTE)
                """
            )
            overdue_60m = (await cur.fetchone())["n"]

        return {
            "ok": True,
            "today_new_tickets": today_new,
            "open_count": open_cnt,
            "pending_count": pending_cnt,
            "overdue_60m": overdue_60m,
        }
