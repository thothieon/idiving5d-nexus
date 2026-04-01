# app/routes_sessions.py  ── idiving5d-OctoFlow v260310
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


class TransitionBody(BaseModel):
    status: str
    note: str | None = None


class BookingBody(BaseModel):
    name:         str | None = None
    phone:        str | None = None
    email:        str | None = None
    course_item:  str | None = None
    booking_date: str | None = None
    note:         str | None = None


class BookingConfirmBody(BaseModel):
    status: str


# ── 狀態機 Endpoints ─────────────────────────────────────────

# 取得指定 ticket 目前的狀態及可允許的下一步轉換清單
@router.get("/tickets/{ticket_id}/status")
async def get_ticket_status(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
):
    async with get_conn() as conn:
        current = await get_ticket_current_status(conn, ticket_id)
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


# 手動觸發 ticket 狀態轉換（先驗證合法性再執行），並記錄操作員工
@router.post("/tickets/{ticket_id}/transition")
async def ticket_transition(
    ticket_id: int,
    body: TransitionBody,
    staff: dict = Depends(get_current_staff),
):
    async with get_conn() as conn:
        current = await get_ticket_current_status(conn, ticket_id)
        validate_transition(current, body.status)

        await transition_ticket_status(
            conn, ticket_id,
            new_status   = body.status,
            triggered_by = "staff",
            staff_id     = int(staff["staff_id"]),
            note         = body.note,
        )
        await conn.commit()
        return {
            "ok": True,
            "from":       current,
            "from_label": STATUS_LABEL.get(current, current),
            "to":         body.status,
            "to_label":   STATUS_LABEL.get(body.status, body.status),
        }


# 取得指定 ticket 的狀態變更歷史記錄，含操作員工與備註
@router.get("/tickets/{ticket_id}/sessions")
async def get_ticket_sessions(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
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
            rows = await cur.fetchall()
        for r in rows:
            r["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
        return {"ok": True, "items": rows}


# 取得各非結案狀態的 ticket 數量摘要統計
@router.get("/tickets/status_summary")
async def tickets_status_summary(staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT current_status, COUNT(*) AS cnt
                FROM tickets
                WHERE current_status != 'closed'
                GROUP BY current_status
                """
            )
            rows = await cur.fetchall()
        result = {r["current_status"]: r["cnt"] for r in rows}
        for s in VALID_TRANSITIONS:
            if s not in result and s != "closed":
                result[s] = 0
        return {"ok": True, "summary": result}


# ── 報名/預約 Endpoints ──────────────────────────────────────

# 取得指定 ticket 的報名/預約資料
@router.get("/tickets/{ticket_id}/booking")
async def get_booking(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM bookings WHERE ticket_id=%s LIMIT 1",
                (ticket_id,)
            )
            row = await cur.fetchone()
        return {"ok": True, "booking": row}


# 新增或更新指定 ticket 的報名/預約資料，並同步更新客戶基本資料
@router.post("/tickets/{ticket_id}/booking")
async def upsert_booking(
    ticket_id: int,
    body: BookingBody,
    staff: dict = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT c.id AS customer_id
                FROM customers c
                JOIN conversations cv ON cv.channel_id = c.line_user_id
                JOIN tickets t ON t.conversation_id = cv.id
                WHERE t.id = %s LIMIT 1
                """,
                (ticket_id,)
            )
            cust = await cur.fetchone()
            customer_id = cust["customer_id"] if cust else None

            if customer_id and (body.name or body.phone or body.email):
                update_parts = []
                update_vals  = []
                if body.name:  update_parts.append("display_name=%s"); update_vals.append(body.name)
                if body.phone: update_parts.append("phone=%s");        update_vals.append(body.phone)
                if body.email: update_parts.append("email=%s");        update_vals.append(body.email)
                if update_parts:
                    await cur.execute(
                        f"UPDATE customers SET {', '.join(update_parts)}, updated_at=NOW() WHERE id=%s",
                        (*update_vals, customer_id)
                    )

            await cur.execute(
                "SELECT id FROM bookings WHERE ticket_id=%s LIMIT 1",
                (ticket_id,)
            )
            existing = await cur.fetchone()

            if existing:
                await cur.execute(
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
                await cur.execute(
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

        current = await get_ticket_current_status(conn, ticket_id)
        if current in ("in_progress", "collecting"):
            await transition_ticket_status(
                conn, ticket_id,
                new_status   = "booking",
                triggered_by = "staff",
                staff_id     = int(staff["staff_id"]),
                note         = "填寫報名資料",
            )

        await conn.commit()
        return {"ok": True}


# 確認或取消報名，確認時自動將 ticket 狀態轉換為結案
@router.post("/tickets/{ticket_id}/booking/confirm")
async def confirm_booking(
    ticket_id: int,
    body: BookingConfirmBody,
    staff: dict = Depends(get_current_staff),
):
    if body.status not in ("confirmed", "cancelled"):
        raise HTTPException(status_code=400, detail="status 必須是 confirmed 或 cancelled")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE bookings SET status=%s, updated_at=NOW() WHERE ticket_id=%s",
                (body.status, ticket_id)
            )

        if body.status == "confirmed":
            await transition_ticket_status(
                conn, ticket_id,
                new_status   = "closed",
                triggered_by = "staff",
                staff_id     = int(staff["staff_id"]),
                note         = "報名確認，自動結案",
            )

        await conn.commit()
        return {"ok": True, "booking_status": body.status}


# ── Active Tickets Polling ────────────────────────────────────

# 列出所有未結案的 ticket，含最後客戶訊息與等待分鐘數，支援分頁
@router.get("/tickets/active")
async def list_active_tickets(
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    t.id AS ticket_id,
                    t.current_status,
                    t.subject,
                    t.opened_at,
                    t.last_customer_message_at,
                    c.channel_type,
                    c.channel_id,
                    COALESCE(cu.display_name, lc.display_name) AS display_name,
                    COALESCE(cu.customer_name, lc.custom_name) AS customer_name,
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
                LEFT JOIN customers cu ON cu.line_user_id = c.channel_id AND c.channel_type = 'user'
                LEFT JOIN line_channels lc ON lc.channel_id = c.channel_id
                                          AND c.channel_type IN ('group', 'room')
                LEFT JOIN assignments a ON a.ticket_id = t.id AND a.status = 'active'
                WHERE t.current_status != 'closed'
                ORDER BY COALESCE(t.last_customer_message_at, t.opened_at) DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset)
            )
            rows = await cur.fetchall()

        for r in rows:
            r["status_label"] = STATUS_LABEL.get(r["current_status"], r["current_status"])
            r["is_overdue"]   = (r["minutes_since_last_message"] or 0) > 60

        return {"ok": True, "items": rows, "limit": limit, "offset": offset}
