# app/routes_sessions.py
# ============================================================
# 狀態機 + 報名/預約 相關 API
# main.py 加上：
#   from app.routes_sessions import router as sessions_router
#   app.include_router(sessions_router, prefix="/admin/api")
# ============================================================

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db import get_conn
from app.auth_staff import get_current_staff
from app.session_manager import (
    get_ticket_current_status,
    transition_ticket_status,
    validate_transition,
    STATUS_LABEL,
    VALID_TRANSITIONS,
)

router = APIRouter()


# ── Pydantic Models ──────────────────────────────────────────

class TransitionBody(BaseModel):
    status: str
    note: str | None = None


class BookingBody(BaseModel):
    name:         str | None = None
    phone:        str | None = None
    email:        str | None = None
    course_item:  str | None = None
    booking_date: str | None = None     # YYYY-MM-DD
    note:         str | None = None


class BookingConfirmBody(BaseModel):
    status: str     # confirmed / cancelled


# ── 狀態機 Endpoints ─────────────────────────────────────────

@router.get("/tickets/{ticket_id}/status")
def get_ticket_status(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
):
    """取得目前狀態 + 允許的下一步"""
    conn = get_conn()
    try:
        current = get_ticket_current_status(conn, ticket_id)
        allowed = VALID_TRANSITIONS.get(current, [])
        return {
            "ok": True,
            "current": current,
            "current_label": STATUS_LABEL.get(current, current),
            "allowed_next": [
                {"status": s, "label": STATUS_LABEL.get(s, s)}
                for s in allowed
            ],
        }
    finally:
        conn.close()


@router.post("/tickets/{ticket_id}/transition")
def ticket_transition(
    ticket_id: int,
    body: TransitionBody,
    staff: dict = Depends(get_current_staff),
):
    """
    客服手動切換 ticket 狀態
    例如：接手 → in_progress、開始收資料 → collecting
    """
    conn = get_conn()
    try:
        current = get_ticket_current_status(conn, ticket_id)
        validate_transition(current, body.status)   # 不合法直接 raise

        transition_ticket_status(
            conn, ticket_id,
            new_status   = body.status,
            triggered_by = "staff",
            staff_id     = int(staff["staff_id"]),
            note         = body.note,
        )
        conn.commit()
        return {
            "ok": True,
            "from":       current,
            "from_label": STATUS_LABEL.get(current, current),
            "to":         body.status,
            "to_label":   STATUS_LABEL.get(body.status, body.status),
        }
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/tickets/{ticket_id}/sessions")
def get_ticket_sessions(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
):
    """取得 ticket 完整狀態變化歷史"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    cs.id, cs.status, cs.triggered_by,
                    cs.note, cs.created_at,
                    s.name AS staff_name
                FROM conversation_sessions cs
                LEFT JOIN staff s ON s.id = cs.staff_id
                WHERE cs.ticket_id = %s
                ORDER BY cs.id ASC
                """,
                (ticket_id,)
            )
            rows = cur.fetchall()
        # 補上中文 label
        for r in rows:
            r["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
        return {"ok": True, "items": rows}
    finally:
        conn.close()


@router.get("/tickets/status_summary")
def tickets_status_summary(
    staff: dict = Depends(get_current_staff),
):
    """
    各狀態的 ticket 數量（給後台 dashboard 用）
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT current_status, COUNT(*) AS cnt
                FROM tickets
                WHERE current_status != 'closed'
                GROUP BY current_status
                """
            )
            rows = cur.fetchall()
        result = {r["current_status"]: r["cnt"] for r in rows}
        # 補上 0 的狀態
        for s in VALID_TRANSITIONS:
            if s not in result and s != "closed":
                result[s] = 0
        return {"ok": True, "summary": result}
    finally:
        conn.close()


# ── 報名/預約 Endpoints ──────────────────────────────────────

@router.get("/tickets/{ticket_id}/booking")
def get_booking(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM bookings WHERE ticket_id=%s LIMIT 1",
                (ticket_id,)
            )
            row = cur.fetchone()
        return {"ok": True, "booking": row}
    finally:
        conn.close()


@router.post("/tickets/{ticket_id}/booking")
def upsert_booking(
    ticket_id: int,
    body: BookingBody,
    staff: dict = Depends(get_current_staff),
):
    """
    建立或更新報名資料。
    同時自動把 ticket 推進到 booking 狀態（如果還不是的話）
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 取 customer_id
            cur.execute(
                """
                SELECT c.id AS customer_id
                FROM customers c
                JOIN conversations cv ON cv.channel_id = c.line_user_id
                JOIN tickets t ON t.conversation_id = cv.id
                WHERE t.id = %s LIMIT 1
                """,
                (ticket_id,)
            )
            cust = cur.fetchone()
            customer_id = cust["customer_id"] if cust else None

            # 同步更新 customers 基本資料（有填就更新）
            if customer_id and (body.name or body.phone or body.email):
                update_parts = []
                update_vals  = []
                if body.name:  update_parts.append("display_name=%s"); update_vals.append(body.name)
                if body.phone: update_parts.append("phone=%s");        update_vals.append(body.phone)
                if body.email: update_parts.append("email=%s");        update_vals.append(body.email)
                if update_parts:
                    cur.execute(
                        f"UPDATE customers SET {', '.join(update_parts)}, updated_at=NOW() WHERE id=%s",
                        (*update_vals, customer_id)
                    )

            # upsert bookings
            cur.execute(
                "SELECT id FROM bookings WHERE ticket_id=%s LIMIT 1",
                (ticket_id,)
            )
            existing = cur.fetchone()

            if existing:
                cur.execute(
                    """
                    UPDATE bookings SET
                        name=%s, phone=%s, email=%s,
                        course_item=%s, booking_date=%s, booking_note=%s,
                        updated_at=NOW()
                    WHERE ticket_id=%s
                    """,
                    (body.name, body.phone, body.email,
                     body.course_item, body.booking_date, body.note,
                     ticket_id)
                )
            else:
                cur.execute(
                    """
                    INSERT INTO bookings
                      (ticket_id, customer_id, name, phone, email,
                       course_item, booking_date, booking_note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (ticket_id, customer_id,
                     body.name, body.phone, body.email,
                     body.course_item, body.booking_date, body.note)
                )

        # 自動推進到 booking 狀態
        current = get_ticket_current_status(conn, ticket_id)
        if current in ("in_progress", "collecting"):
            transition_ticket_status(
                conn, ticket_id,
                new_status   = "booking",
                triggered_by = "staff",
                staff_id     = int(staff["staff_id"]),
                note         = "填寫報名資料",
            )

        conn.commit()
        return {"ok": True}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/tickets/{ticket_id}/booking/confirm")
def confirm_booking(
    ticket_id: int,
    body: BookingConfirmBody,
    staff: dict = Depends(get_current_staff),
):
    """確認或取消報名"""
    if body.status not in ("confirmed", "cancelled"):
        raise HTTPException(status_code=400, detail="status 必須是 confirmed 或 cancelled")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE bookings SET status=%s, updated_at=NOW() WHERE ticket_id=%s",
                (body.status, ticket_id)
            )

        # 報名確認 → 結案
        if body.status == "confirmed":
            transition_ticket_status(
                conn, ticket_id,
                new_status   = "closed",
                triggered_by = "staff",
                staff_id     = int(staff["staff_id"]),
                note         = "報名確認，自動結案",
            )

        conn.commit()
        return {"ok": True, "booking_status": body.status}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── Angular Polling 專用 endpoint ────────────────────────────

@router.get("/tickets/active")
def list_active_tickets(
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """
    給 Angular polling 用：取所有未結案的 ticket
    依 last_customer_message_at 排序（最新來訊排最上面）
    包含 current_status 讓前端可以用不同顏色標示
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    t.id AS ticket_id,
                    t.current_status,
                    t.subject,
                    t.opened_at,
                    t.last_customer_message_at,
                    c.channel_type,
                    c.channel_id,
                    cu.display_name,
                    cu.phone,
                    a.agent_name AS active_agent,
                    (
                        SELECT mr.text
                        FROM messages_raw mr
                        WHERE mr.ticket_id = t.id
                          AND mr.direction = 'in'
                          AND mr.message_type = 'text'
                        ORDER BY mr.id DESC LIMIT 1
                    ) AS last_customer_text,
                    TIMESTAMPDIFF(
                        MINUTE,
                        COALESCE(t.last_customer_message_at, t.opened_at),
                        NOW()
                    ) AS minutes_since_last_message
                FROM tickets t
                JOIN conversations c ON c.id = t.conversation_id
                LEFT JOIN customers cu ON cu.line_user_id = c.channel_id
                LEFT JOIN assignments a ON a.ticket_id = t.id AND a.status = 'active'
                WHERE t.current_status != 'closed'
                ORDER BY COALESCE(t.last_customer_message_at, t.opened_at) DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset)
            )
            rows = cur.fetchall()

        # 補上 label 和逾期旗標（超過 60 分鐘未回覆）
        for r in rows:
            r["status_label"] = STATUS_LABEL.get(r["current_status"], r["current_status"])
            r["is_overdue"]   = (r["minutes_since_last_message"] or 0) > 60

        return {"ok": True, "items": rows, "limit": limit, "offset": offset}
    finally:
        conn.close()
