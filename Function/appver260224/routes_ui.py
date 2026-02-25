# app/routes_ui.py
import os
import pymysql
from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from app.auth_staff import get_current_staff, get_conn

router = APIRouter()

# ✅ 你 templates 放哪裡就填哪裡
# 常見：/app/app/templates 或 /app/templates
TEMPLATES_DIR = os.environ.get("TEMPLATES_DIR", "app/templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


# ---------------- UI pages ----------------
@router.get("/admin/ui")
def admin_ui_index(
    request: Request,
    staff: dict = Depends(get_current_staff),
):
    return templates.TemplateResponse("admin_index.html", {"request": request, "staff": staff})


@router.get("/admin/uiturn_based")
def admin_uiturn_index_based(
    request: Request,
    staff: dict = Depends(get_current_staff),
):
    return templates.TemplateResponse("admin_turn_based.html", {"request": request, "staff": staff})


@router.get("/admin/uiturn/t/{ticket_id}")
def admin_uiturn_ticket(
    ticket_id: int,
    request: Request,
    staff: dict = Depends(get_current_staff),
):
    return templates.TemplateResponse(
        "admin_ticket_turn_based.html",
        {"request": request, "ticket_id": ticket_id, "staff": staff},
    )


# ---------------- Admin API (UI needs) ----------------
@router.get("/admin/api/dashboard")
def admin_api_dashboard(
    staff: dict = Depends(get_current_staff),
):
    # 原本 Flask 版同樣需要 staff token 才能進 :contentReference[oaicite:4]{index=4}
    # 這裡直接沿用 staff token 機制即可（不再用 ADMIN_TOKEN，避免跟 X-Admin-Token 衝突）

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM tickets
                WHERE COALESCE(opened_at, created_at) >= DATE_SUB(NOW(), INTERVAL 1 DAY)
                """
            )
            today_new = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM tickets WHERE status='open'")
            open_cnt = cur.fetchone()["n"]

            cur.execute("SELECT COUNT(*) AS n FROM tickets WHERE status='pending'")
            pending_cnt = cur.fetchone()["n"]

            cur.execute(
                """
                SELECT COUNT(*) AS n
                FROM tickets
                WHERE status IN ('open','pending')
                  AND COALESCE(last_customer_message_at, opened_at, created_at) < DATE_SUB(NOW(), INTERVAL 60 MINUTE)
                """
            )
            overdue_60m = cur.fetchone()["n"]

        return {
            "ok": True,
            "today_new_tickets": today_new,
            "open_count": open_cnt,
            "pending_count": pending_cnt,
            "overdue_60m": overdue_60m,
        }
    finally:
        conn.close()
