# app/routes_registration.py  ── idiving5d-OctoFlow
# ============================================================
# 報名系統 API
#
# Public  (無需驗證):
#   GET  /api/reg/courses                    課程/活動清單
#   GET  /api/reg/courses/{id}/sessions      梯次列表
#   POST /api/reg/customers/lookup           查詢既有客戶
#   POST /api/reg/registrations              送出報名
#
# Admin   (需 X-Admin-Token):
#   GET  /admin/api/reg/registrations        報名名單
#   PUT  /admin/api/reg/registrations/{id}   更新狀態（確認/取消/候補升正）
#   GET  /admin/api/reg/registrations/export 匯出 Excel
#   GET  /admin/api/reg/sessions             梯次管理列表
#   POST /admin/api/reg/sessions             新增梯次
#   PUT  /admin/api/reg/sessions/{id}        修改梯次
# ============================================================
import io
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db import get_conn
from app.auth_staff import get_current_staff

public_router = APIRouter()
admin_router  = APIRouter()


# ── Pydantic Models ──────────────────────────────────────────

class CourseCreate(BaseModel):
    course_code:  str = Field(..., max_length=20)
    title:        str = Field(..., max_length=100)
    type:         str = 'course'
    description:  Optional[str] = None
    require_form: int = 0
    is_active:    int = 1
    sort_order:   int = 0


class CourseUpdate(BaseModel):
    course_code:  Optional[str] = Field(None, max_length=20)
    title:        Optional[str] = Field(None, max_length=100)
    type:         Optional[str] = None
    description:  Optional[str] = None
    require_form: Optional[int] = None
    is_active:    Optional[int] = None
    sort_order:   Optional[int] = None


class CustomerLookup(BaseModel):
    mid:       Optional[str] = None
    name:      Optional[str] = None
    id_number: Optional[str] = None


class CustomerCreate(BaseModel):
    name:               str  = Field(..., max_length=50)
    id_number:          str  = Field(..., max_length=20)
    phone:              str  = Field(..., max_length=20)   # 行動電話
    home_phone:         Optional[str] = Field(None, max_length=20)
    email:              Optional[str] = Field(None, max_length=100)
    mid:                Optional[str] = Field(None, max_length=30)
    nickname:           Optional[str] = Field(None, max_length=50)
    name_en:            Optional[str] = Field(None, max_length=100)
    birth_date:         Optional[str] = None   # YYYY-MM-DD
    nationality:        Optional[str] = Field(None, max_length=50)
    blood_type:         Optional[str] = Field(None, max_length=5)
    address:            Optional[str] = Field(None, max_length=255)
    emergency_contact:  Optional[str] = Field(None, max_length=50)
    emergency_phone:    Optional[str] = Field(None, max_length=20)
    height:             Optional[float] = None
    weight:             Optional[float] = None
    shoe_size:          Optional[float] = None
    vision_left:        Optional[float] = None
    vision_right:       Optional[float] = None
    payment_date:       Optional[str] = None   # YYYY-MM-DD
    membership_expiry:  Optional[str] = None   # YYYY-MM-DD


class CustomerUpdate(BaseModel):
    name:               Optional[str] = Field(None, max_length=50)
    phone:              Optional[str] = Field(None, max_length=20)
    home_phone:         Optional[str] = Field(None, max_length=20)
    email:              Optional[str] = Field(None, max_length=100)
    mid:                Optional[str] = Field(None, max_length=30)
    nickname:           Optional[str] = Field(None, max_length=50)
    name_en:            Optional[str] = Field(None, max_length=100)
    birth_date:         Optional[str] = None
    nationality:        Optional[str] = Field(None, max_length=50)
    blood_type:         Optional[str] = Field(None, max_length=5)
    address:            Optional[str] = Field(None, max_length=255)
    emergency_contact:  Optional[str] = Field(None, max_length=50)
    emergency_phone:    Optional[str] = Field(None, max_length=20)
    height:             Optional[float] = None
    weight:             Optional[float] = None
    shoe_size:          Optional[float] = None
    vision_left:        Optional[float] = None
    vision_right:       Optional[float] = None
    payment_date:       Optional[str] = None
    membership_expiry:  Optional[str] = None


class RegistrationCreate(BaseModel):
    session_id:  int
    customer_id: Optional[int] = None   # 已查到既有客戶
    customer:    Optional[CustomerCreate] = None  # 新客戶資料
    notes:       Optional[str] = None
    health_form: Optional[dict] = None  # 健康申明答案


class RegistrationStatusUpdate(BaseModel):
    reg_status:     Optional[str] = None   # confirmed / cancelled / waitlist / pending
    payment_status: Optional[str] = None   # paid / unpaid
    notes:          Optional[str] = None


class SessionCreate(BaseModel):
    course_id:         int
    label:             str = Field(..., max_length=100)
    start_date:        str   # YYYY-MM-DD
    end_date:          str   # YYYY-MM-DD
    capacity:          int = 8
    waitlist_capacity: int = 0
    status:            str = 'open'
    note:              Optional[str] = Field(None, max_length=255)


class SessionUpdate(BaseModel):
    label:             Optional[str] = Field(None, max_length=100)
    start_date:        Optional[str] = None
    end_date:          Optional[str] = None
    capacity:          Optional[int] = None
    waitlist_capacity: Optional[int] = None
    status:            Optional[str] = None
    note:              Optional[str] = Field(None, max_length=255)


# ── Public: 課程/活動清單 ────────────────────────────────────

@public_router.get("/reg/courses")
async def list_courses(type: Optional[str] = None):
    """回傳上架中的課程或活動清單"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            if type in ('course', 'activity'):
                await cur.execute(
                    "SELECT id, course_code, title, type, description, require_form "
                    "FROM reg_courses WHERE is_active=1 AND type=%s ORDER BY sort_order",
                    (type,)
                )
            else:
                await cur.execute(
                    "SELECT id, course_code, title, type, description, require_form "
                    "FROM reg_courses WHERE is_active=1 ORDER BY sort_order"
                )
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ── Public: 梯次列表 ─────────────────────────────────────────

@public_router.get("/reg/courses/{course_id}/sessions")
async def list_sessions(course_id: int):
    """回傳指定課程的可報名梯次（含名額資訊）"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            # 梯次基本資料
            await cur.execute(
                "SELECT id, label, start_date, end_date, capacity, waitlist_capacity, status, note "
                "FROM reg_sessions WHERE course_id=%s ORDER BY start_date",
                (course_id,)
            )
            sessions = await cur.fetchall()

            result = []
            for s in sessions:
                sid = s['id']
                # 正取人數
                await cur.execute(
                    "SELECT COUNT(*) AS cnt FROM registrations "
                    "WHERE session_id=%s AND reg_status IN ('pending','confirmed')",
                    (sid,)
                )
                confirmed_row = await cur.fetchone()
                confirmed_count = confirmed_row['cnt']

                # 候補人數
                await cur.execute(
                    "SELECT COUNT(*) AS cnt FROM registrations "
                    "WHERE session_id=%s AND reg_status='waitlist'",
                    (sid,)
                )
                waitlist_row = await cur.fetchone()
                waitlist_count = waitlist_row['cnt']

                result.append({
                    **dict(s),
                    'confirmed_count': confirmed_count,
                    'available':       max(0, s['capacity'] - confirmed_count),
                    'waitlist_count':  waitlist_count,
                    'waitlist_available': (
                        max(0, s['waitlist_capacity'] - waitlist_count)
                        if s['waitlist_capacity'] > 0 else 0
                    ),
                })
    return result


# ── Public: 查詢既有客戶 ─────────────────────────────────────

@public_router.post("/reg/customers/lookup")
async def lookup_customer(body: CustomerLookup):
    """依 MID 或 身分證字號 查詢既有客戶，找到回傳完整資料，找不到回傳 null"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            if body.mid:
                await cur.execute(
                    "SELECT id, name, id_number, mobile_phone AS phone, home_phone, email, mid, "
                    "nickname, name_en, birth_date, nationality, blood_type, address, "
                    "emergency_contact, emergency_phone, height, weight, shoe_size, "
                    "vision_left, vision_right "
                    "FROM reg_customers WHERE mid=%s LIMIT 1",
                    (body.mid,)
                )
            elif body.id_number:
                await cur.execute(
                    "SELECT id, name, id_number, mobile_phone AS phone, home_phone, email, mid, "
                    "nickname, name_en, birth_date, nationality, blood_type, address, "
                    "emergency_contact, emergency_phone, height, weight, shoe_size, "
                    "vision_left, vision_right "
                    "FROM reg_customers WHERE id_number=%s LIMIT 1",
                    (body.id_number,)
                )
            else:
                raise HTTPException(400, "請提供 mid 或 id_number")

            row = await cur.fetchone()
    return dict(row) if row else None


# ── Public: 送出報名 ─────────────────────────────────────────

@public_router.post("/reg/registrations", status_code=201)
async def create_registration(body: RegistrationCreate):
    """送出報名，自動判斷正取/候補"""
    if body.customer_id is None and body.customer is None:
        raise HTTPException(400, "請提供 customer_id 或 customer 資料")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            # 取得梯次資訊
            await cur.execute(
                "SELECT id, capacity, waitlist_capacity, status "
                "FROM reg_sessions WHERE id=%s FOR UPDATE",
                (body.session_id,)
            )
            session = await cur.fetchone()
            if not session:
                raise HTTPException(404, "梯次不存在")
            if session['status'] == 'closed':
                raise HTTPException(409, "此梯次已關閉報名")

            # 計算目前正取人數
            await cur.execute(
                "SELECT COUNT(*) AS cnt FROM registrations "
                "WHERE session_id=%s AND reg_status IN ('pending','confirmed')",
                (body.session_id,)
            )
            confirmed_count = (await cur.fetchone())['cnt']

            # 計算目前候補人數
            await cur.execute(
                "SELECT COUNT(*) AS cnt FROM registrations "
                "WHERE session_id=%s AND reg_status='waitlist'",
                (body.session_id,)
            )
            waitlist_count = (await cur.fetchone())['cnt']

            # 判斷可否報名
            is_full = confirmed_count >= session['capacity']
            waitlist_full = (
                session['waitlist_capacity'] == 0 or
                waitlist_count >= session['waitlist_capacity']
            )
            if is_full and waitlist_full:
                raise HTTPException(409, "名額已滿且候補已滿，無法報名")

            # 建立或取得 customer_id
            customer_id = body.customer_id
            if customer_id is None:
                c = body.customer
                # 檢查身分證是否已存在
                await cur.execute(
                    "SELECT id FROM reg_customers WHERE id_number=%s LIMIT 1",
                    (c.id_number,)
                )
                existing = await cur.fetchone()
                if existing:
                    customer_id = existing['id']
                    await cur.execute(
                        "UPDATE reg_customers SET name=%s, mobile_phone=%s, home_phone=%s, email=%s, mid=%s, "
                        "nickname=%s, name_en=%s, birth_date=%s, nationality=%s, blood_type=%s, "
                        "address=%s, emergency_contact=%s, emergency_phone=%s, "
                        "height=%s, weight=%s, shoe_size=%s, vision_left=%s, vision_right=%s, "
                        "payment_date=%s, membership_expiry=%s, updated_at=NOW() "
                        "WHERE id=%s",
                        (c.name, c.phone, c.home_phone, c.email, c.mid,
                         c.nickname, c.name_en, c.birth_date, c.nationality, c.blood_type,
                         c.address, c.emergency_contact, c.emergency_phone,
                         c.height, c.weight, c.shoe_size, c.vision_left, c.vision_right,
                         c.payment_date, c.membership_expiry, customer_id)
                    )
                else:
                    await cur.execute(
                        "INSERT INTO reg_customers "
                        "(name, id_number, mobile_phone, home_phone, email, mid, "
                        " nickname, name_en, birth_date, nationality, blood_type, "
                        " address, emergency_contact, emergency_phone, "
                        " height, weight, shoe_size, vision_left, vision_right, "
                        " payment_date, membership_expiry) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (c.name, c.id_number, c.phone, c.home_phone, c.email, c.mid,
                         c.nickname, c.name_en, c.birth_date, c.nationality, c.blood_type,
                         c.address, c.emergency_contact, c.emergency_phone,
                         c.height, c.weight, c.shoe_size, c.vision_left, c.vision_right,
                         c.payment_date, c.membership_expiry)
                    )
                    customer_id = cur.lastrowid

            # 檢查同一客戶是否已報同梯次
            await cur.execute(
                "SELECT id, reg_status FROM registrations "
                "WHERE session_id=%s AND customer_id=%s AND reg_status != 'cancelled' LIMIT 1",
                (body.session_id, customer_id)
            )
            dup = await cur.fetchone()
            if dup:
                raise HTTPException(409, f"此客戶已報名此梯次（狀態：{dup['reg_status']}）")

            # 決定狀態與候補順位
            if not is_full:
                reg_status        = 'pending'
                waitlist_position = None
            else:
                reg_status        = 'waitlist'
                waitlist_position = waitlist_count + 1

            health_json = json.dumps(body.health_form, ensure_ascii=False) if body.health_form else None
            await cur.execute(
                "INSERT INTO registrations "
                "(session_id, customer_id, reg_status, waitlist_position, notes, health_form) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (body.session_id, customer_id, reg_status, waitlist_position, body.notes, health_json)
            )
            reg_id = cur.lastrowid

        await conn.commit()

    return {
        "id":               reg_id,
        "reg_status":       reg_status,
        "waitlist_position": waitlist_position,
        "message": "候補成功" if reg_status == 'waitlist' else "報名成功，等待店家確認",
    }


# ── Admin: 報名名單 ───────────────────────────────────────────

@admin_router.get("/reg/registrations")
async def admin_list_registrations(
    session_id:  Optional[int] = None,
    course_id:   Optional[int] = None,
    reg_status:  Optional[str] = None,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            sql = """
                SELECT
                    r.id, r.reg_status, r.payment_status,
                    r.waitlist_position, r.notes, r.health_form,
                    r.registered_at, r.confirmed_at,
                    r.transfer_bank, r.transfer_date, r.transfer_note,
                    r.payment_submitted_at,
                    c.id AS customer_id,
                    c.name, c.id_number,
                    c.mobile_phone AS phone, c.home_phone, c.email, c.mid,
                    c.nickname, c.name_en, c.birth_date, c.nationality, c.blood_type,
                    c.address, c.emergency_contact, c.emergency_phone,
                    c.height, c.weight, c.shoe_size, c.vision_left, c.vision_right,
                    c.payment_date, c.membership_expiry,
                    s.label AS session_label, s.start_date, s.end_date,
                    co.title AS course_title, co.course_code
                FROM registrations r
                JOIN reg_customers c  ON c.id  = r.customer_id
                JOIN reg_sessions  s  ON s.id  = r.session_id
                JOIN reg_courses   co ON co.id = s.course_id
                WHERE 1=1
            """
            params = []
            if session_id:
                sql += " AND r.session_id=%s"
                params.append(session_id)
            if course_id:
                sql += " AND s.course_id=%s"
                params.append(course_id)
            if reg_status:
                sql += " AND r.reg_status=%s"
                params.append(reg_status)
            sql += " ORDER BY r.registered_at DESC"
            await cur.execute(sql, params)
            rows = await cur.fetchall()

    result = []
    for r in rows:
        row = dict(r)
        if isinstance(row.get('health_form'), str):
            try:
                row['health_form'] = json.loads(row['health_form'])
            except Exception:
                row['health_form'] = None
        result.append(row)
    return result


# ── Admin: 更新報名狀態 ───────────────────────────────────────

@admin_router.put("/reg/registrations/{reg_id}")
async def admin_update_registration(
    reg_id: int,
    body: RegistrationStatusUpdate,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, session_id, reg_status FROM registrations WHERE id=%s FOR UPDATE",
                (reg_id,)
            )
            reg = await cur.fetchone()
            if not reg:
                raise HTTPException(404, "報名記錄不存在")

            updates, params = [], []

            if body.reg_status is not None:
                if body.reg_status not in ('pending', 'confirmed', 'cancelled', 'waitlist'):
                    raise HTTPException(400, "無效的 reg_status")
                updates.append("reg_status=%s")
                params.append(body.reg_status)

                # 確認時記錄時間
                if body.reg_status == 'confirmed':
                    updates.append("confirmed_at=NOW()")

                # 取消時，推進候補第一位
                if body.reg_status == 'cancelled' and reg['reg_status'] in ('pending', 'confirmed'):
                    await cur.execute(
                        "SELECT id FROM registrations "
                        "WHERE session_id=%s AND reg_status='waitlist' "
                        "ORDER BY waitlist_position ASC LIMIT 1",
                        (reg['session_id'],)
                    )
                    next_waitlist = await cur.fetchone()
                    if next_waitlist:
                        await cur.execute(
                            "UPDATE registrations "
                            "SET reg_status='pending', waitlist_position=NULL, updated_at=NOW() "
                            "WHERE id=%s",
                            (next_waitlist['id'],)
                        )
                        # 重排剩餘候補順位
                        await cur.execute(
                            "SELECT id FROM registrations "
                            "WHERE session_id=%s AND reg_status='waitlist' "
                            "ORDER BY waitlist_position ASC",
                            (reg['session_id'],)
                        )
                        remaining = await cur.fetchall()
                        for pos, row in enumerate(remaining, start=1):
                            await cur.execute(
                                "UPDATE registrations SET waitlist_position=%s WHERE id=%s",
                                (pos, row['id'])
                            )

            if body.payment_status is not None:
                if body.payment_status not in ('unpaid', 'paid'):
                    raise HTTPException(400, "無效的 payment_status")
                updates.append("payment_status=%s")
                params.append(body.payment_status)

            if body.notes is not None:
                updates.append("notes=%s")
                params.append(body.notes)

            if not updates:
                raise HTTPException(400, "沒有要更新的欄位")

            updates.append("updated_at=NOW()")
            params.append(reg_id)
            await cur.execute(
                f"UPDATE registrations SET {', '.join(updates)} WHERE id=%s",
                params
            )
        await conn.commit()
    return {"ok": True}


# ── Admin: 匯出 Excel ────────────────────────────────────────

@admin_router.get("/reg/registrations/export")
async def admin_export_registrations(
    session_id: Optional[int] = None,
    course_id:  Optional[int] = None,
    reg_status: Optional[str] = None,
    staff = Depends(get_current_staff),
):
    try:
        import openpyxl
    except ImportError:
        raise HTTPException(500, "請安裝 openpyxl：pip install openpyxl")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            sql = """
                SELECT
                    r.id, co.title AS course_title, s.label AS session_label,
                    s.start_date, s.end_date,
                    c.name, c.id_number, c.mobile_phone AS phone, c.home_phone, c.email, c.mid,
                    c.nickname, c.name_en, c.birth_date, c.nationality, c.blood_type,
                    c.address, c.emergency_contact, c.emergency_phone,
                    c.height, c.weight, c.shoe_size, c.vision_left, c.vision_right,
                    c.payment_date, c.membership_expiry,
                    r.reg_status, r.payment_status,
                    r.waitlist_position, r.registered_at, r.confirmed_at, r.notes
                FROM registrations r
                JOIN reg_customers c  ON c.id  = r.customer_id
                JOIN reg_sessions  s  ON s.id  = r.session_id
                JOIN reg_courses   co ON co.id = s.course_id
                WHERE 1=1
            """
            params = []
            if session_id:
                sql += " AND r.session_id=%s"; params.append(session_id)
            if course_id:
                sql += " AND s.course_id=%s";  params.append(course_id)
            if reg_status:
                sql += " AND r.reg_status=%s"; params.append(reg_status)
            sql += " ORDER BY s.start_date, r.reg_status, r.waitlist_position, r.registered_at"
            await cur.execute(sql, params)
            rows = await cur.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "報名名單"
    headers = [
        "編號", "課程/活動", "梯次", "開始日期", "結束日期",
        "姓名", "身分證", "電話", "Email", "MID",
        "狀態", "付款狀態", "候補順位", "報名時間", "確認時間", "備註"
    ]
    ws.append(headers)

    status_map  = {'pending': '待確認', 'confirmed': '已確認', 'cancelled': '已取消', 'waitlist': '候補'}
    payment_map = {'unpaid': '未付款', 'paid': '已付款'}

    for r in rows:
        ws.append([
            r['id'],
            r['course_title'],
            r['session_label'],
            str(r['start_date']),
            str(r['end_date']),
            r['name'],
            r['id_number'],
            r['phone'],
            r['email'] or '',
            r['mid'] or '',
            status_map.get(r['reg_status'], r['reg_status']),
            payment_map.get(r['payment_status'], r['payment_status']),
            r['waitlist_position'] or '',
            str(r['registered_at']) if r['registered_at'] else '',
            str(r['confirmed_at'])  if r['confirmed_at']  else '',
            r['notes'] or '',
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"registrations_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ── Admin: 梯次管理 ───────────────────────────────────────────

@admin_router.get("/reg/sessions")
async def admin_list_sessions(
    course_id: Optional[int] = None,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            sql = """
                SELECT s.id, s.course_id, co.title AS course_title,
                       s.label, s.start_date, s.end_date,
                       s.capacity, s.waitlist_capacity, s.status, s.note,
                       COUNT(CASE WHEN r.reg_status IN ('pending','confirmed') THEN 1 END) AS confirmed_count,
                       COUNT(CASE WHEN r.reg_status = 'waitlist' THEN 1 END) AS waitlist_count
                FROM reg_sessions s
                JOIN reg_courses co ON co.id = s.course_id
                LEFT JOIN registrations r ON r.session_id = s.id
                WHERE 1=1
            """
            params = []
            if course_id:
                sql += " AND s.course_id=%s"
                params.append(course_id)
            sql += " GROUP BY s.id ORDER BY s.start_date DESC"
            await cur.execute(sql, params)
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@admin_router.post("/reg/sessions", status_code=201)
async def admin_create_session(
    body: SessionCreate,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO reg_sessions "
                "(course_id, label, start_date, end_date, capacity, waitlist_capacity, status, note) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (body.course_id, body.label, body.start_date, body.end_date,
                 body.capacity, body.waitlist_capacity, body.status, body.note)
            )
            new_id = cur.lastrowid
        await conn.commit()
    return {"id": new_id}


@admin_router.put("/reg/sessions/{session_id}")
async def admin_update_session(
    session_id: int,
    body: SessionUpdate,
    staff = Depends(get_current_staff),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            updates, params = [], []
            for field, val in body.model_dump(exclude_none=True).items():
                updates.append(f"{field}=%s")
                params.append(val)
            if not updates:
                raise HTTPException(400, "沒有要更新的欄位")
            updates.append("updated_at=NOW()")
            params.append(session_id)
            await cur.execute(
                f"UPDATE reg_sessions SET {', '.join(updates)} WHERE id=%s",
                params
            )
        await conn.commit()
    return {"ok": True}


# ── Admin: 課程管理 ───────────────────────────────────────────

@admin_router.get("/reg/courses")
async def admin_list_courses(staff = Depends(get_current_staff)):
    """後台取得所有課程（含下架）"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, course_code, title, type, description, "
                "require_form, is_active, sort_order "
                "FROM reg_courses ORDER BY sort_order, id"
            )
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@admin_router.post("/reg/courses", status_code=201)
async def admin_create_course(
    body: CourseCreate,
    staff = Depends(get_current_staff),
):
    if body.type not in ('course', 'activity'):
        raise HTTPException(400, "type 必須為 course 或 activity")
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    "INSERT INTO reg_courses "
                    "(course_code, title, type, description, require_form, is_active, sort_order) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (body.course_code, body.title, body.type,
                     body.description, body.require_form, body.is_active, body.sort_order)
                )
                new_id = cur.lastrowid
            except Exception as e:
                await conn.rollback()
                if "Duplicate" in str(e):
                    raise HTTPException(409, f"課程代碼「{body.course_code}」已存在")
                raise
        await conn.commit()
    return {"id": new_id}


@admin_router.put("/reg/courses/{course_id}")
async def admin_update_course(
    course_id: int,
    body: CourseUpdate,
    staff = Depends(get_current_staff),
):
    if body.type is not None and body.type not in ('course', 'activity'):
        raise HTTPException(400, "type 必須為 course 或 activity")
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            updates, params = [], []
            for field, val in body.model_dump(exclude_none=True).items():
                updates.append(f"{field}=%s")
                params.append(val)
            if not updates:
                raise HTTPException(400, "沒有要更新的欄位")
            updates.append("updated_at=NOW()")
            params.append(course_id)
            try:
                await cur.execute(
                    f"UPDATE reg_courses SET {', '.join(updates)} WHERE id=%s",
                    params
                )
            except Exception as e:
                await conn.rollback()
                if "Duplicate" in str(e):
                    raise HTTPException(409, "課程代碼已被其他課程使用")
                raise
        await conn.commit()
    return {"ok": True}


# ── Admin: 更新客戶個人資料 ───────────────────────────────────

@admin_router.put("/reg/customers/{customer_id}")
async def admin_update_customer(
    customer_id: int,
    body: CustomerUpdate,
    staff = Depends(get_current_staff),
):
    """更新客戶的個人資料欄位"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM reg_customers WHERE id=%s LIMIT 1", (customer_id,))
            if not await cur.fetchone():
                raise HTTPException(404, "客戶不存在")

            FIELD_MAP = {"phone": "mobile_phone"}
            updates, params = [], []
            for field, val in body.model_dump(exclude_unset=True).items():
                col = FIELD_MAP.get(field, field)
                updates.append(f"{col}=%s")
                params.append(val)
            if not updates:
                raise HTTPException(400, "沒有要更新的欄位")
            updates.append("updated_at=NOW()")
            params.append(customer_id)
            await cur.execute(
                f"UPDATE reg_customers SET {', '.join(updates)} WHERE id=%s",
                params
            )
        await conn.commit()
    return {"ok": True}


# ── Admin: 確認報名資料 → 發付款 email ───────────────────────

import secrets
import asyncio
from datetime import timedelta
from app.email_service import send_payment_request, send_registration_complete, FRONTEND_URL

@admin_router.post("/reg/registrations/{reg_id}/confirm-data")
async def admin_confirm_data(
    reg_id: int,
    staff = Depends(get_current_staff),
):
    """員工確認客戶資料，產生付款 token 並發 email"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.id, r.reg_status,
                          c.name, c.email,
                          s.label AS session_label, s.start_date, s.end_date,
                          co.title AS course_title
                   FROM registrations r
                   JOIN reg_customers c  ON c.id  = r.customer_id
                   JOIN reg_sessions  s  ON s.id  = r.session_id
                   JOIN reg_courses   co ON co.id = s.course_id
                   WHERE r.id=%s""",
                (reg_id,)
            )
            reg = await cur.fetchone()
            if not reg:
                raise HTTPException(404, "報名紀錄不存在")
            if reg['reg_status'] not in ('pending', 'waitlist'):
                raise HTTPException(409, f"目前狀態 {reg['reg_status']} 無法確認資料")
            if not reg['email']:
                raise HTTPException(400, "客戶未填寫 email，無法發送通知")

            token   = secrets.token_urlsafe(32)
            expires = datetime.now() + timedelta(days=7)

            await cur.execute(
                "UPDATE registrations SET reg_status='data_confirmed', "
                "payment_token=%s, payment_token_expires_at=%s WHERE id=%s",
                (token, expires, reg_id)
            )
        await conn.commit()

    payment_url = f"{FRONTEND_URL}/#/payment/{token}"
    expire_date = (datetime.now() + timedelta(days=7)).strftime("%Y/%m/%d")
    asyncio.create_task(send_payment_request(
        to_email=reg['email'], name=reg['name'],
        course_title=reg['course_title'], session_label=reg['session_label'],
        start_date=str(reg['start_date']), end_date=str(reg['end_date']),
        payment_url=payment_url, expire_date=expire_date,
    ))
    return {"ok": True, "token": token}


# ── Public: 取得付款頁面資訊（by token）────────────────────────

@public_router.get("/reg/payment/{token}")
async def get_payment_info(token: str):
    """客人用 email 連結進入付款頁，取得報名資訊"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.id, r.reg_status, r.payment_token_expires_at,
                          r.transfer_bank, r.transfer_date, r.transfer_note,
                          c.name,
                          s.label AS session_label, s.start_date, s.end_date,
                          co.title AS course_title
                   FROM registrations r
                   JOIN reg_customers c  ON c.id  = r.customer_id
                   JOIN reg_sessions  s  ON s.id  = r.session_id
                   JOIN reg_courses   co ON co.id = s.course_id
                   WHERE r.payment_token=%s""",
                (token,)
            )
            reg = await cur.fetchone()
    if not reg:
        raise HTTPException(404, "連結無效")
    if reg['reg_status'] == 'payment_submitted':
        return {**dict(reg), "already_submitted": True}
    if reg['reg_status'] != 'data_confirmed':
        raise HTTPException(409, "此連結已失效或報名狀態不正確")
    if reg['payment_token_expires_at'] and datetime.now() > reg['payment_token_expires_at']:
        raise HTTPException(410, "此連結已過期，請聯繫店家重新取得")
    return {**dict(reg), "already_submitted": False}


# ── Public: 客人提交匯款資訊 ─────────────────────────────────

class PaymentSubmit(BaseModel):
    transfer_bank: str = Field(..., max_length=10, description="匯款帳號後5碼")
    transfer_date: str
    transfer_note: Optional[str] = Field(None, max_length=200)

@public_router.post("/reg/payment/{token}")
async def submit_payment(token: str, body: PaymentSubmit):
    """客人填寫匯款資訊"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, reg_status, payment_token_expires_at "
                "FROM registrations WHERE payment_token=%s",
                (token,)
            )
            reg = await cur.fetchone()
            if not reg:
                raise HTTPException(404, "連結無效")
            if reg['reg_status'] == 'payment_submitted':
                raise HTTPException(409, "已提交過匯款資訊")
            if reg['reg_status'] != 'data_confirmed':
                raise HTTPException(409, "此連結狀態不正確")
            if reg['payment_token_expires_at'] and datetime.now() > reg['payment_token_expires_at']:
                raise HTTPException(410, "連結已過期")

            await cur.execute(
                "UPDATE registrations SET reg_status='payment_submitted', "
                "transfer_bank=%s, transfer_date=%s, transfer_note=%s, "
                "payment_submitted_at=NOW() WHERE id=%s",
                (body.transfer_bank, body.transfer_date, body.transfer_note, reg['id'])
            )
        await conn.commit()
    return {"ok": True}


# ── Admin: 確認完成報名 → 發完成 email ───────────────────────

@admin_router.post("/reg/registrations/{reg_id}/confirm-payment")
async def admin_confirm_payment(
    reg_id: int,
    staff = Depends(get_current_staff),
):
    """員工確認匯款，標記報名完成並發 email"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.id, r.reg_status,
                          c.name, c.email,
                          s.label AS session_label, s.start_date, s.end_date,
                          co.title AS course_title
                   FROM registrations r
                   JOIN reg_customers c  ON c.id  = r.customer_id
                   JOIN reg_sessions  s  ON s.id  = r.session_id
                   JOIN reg_courses   co ON co.id = s.course_id
                   WHERE r.id=%s""",
                (reg_id,)
            )
            reg = await cur.fetchone()
            if not reg:
                raise HTTPException(404, "報名紀錄不存在")
            if reg['reg_status'] != 'payment_submitted':
                raise HTTPException(409, f"目前狀態 {reg['reg_status']} 無法確認完成")

            await cur.execute(
                "UPDATE registrations SET reg_status='confirmed', confirmed_at=NOW() WHERE id=%s",
                (reg_id,)
            )
        await conn.commit()

    if reg['email']:
        asyncio.create_task(send_registration_complete(
            to_email=reg['email'], name=reg['name'],
            course_title=reg['course_title'], session_label=reg['session_label'],
            start_date=str(reg['start_date']), end_date=str(reg['end_date']),
        ))
    return {"ok": True}


# ── Admin: 重發確認信 ──────────────────────────────────────────

@admin_router.post("/reg/registrations/{reg_id}/resend-email")
async def admin_resend_email(
    reg_id: int,
    staff = Depends(get_current_staff),
):
    """重發確認 email（付款通知 或 完成通知）"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT r.id, r.reg_status, r.payment_token, r.payment_token_expires_at,
                          c.name, c.email,
                          s.label AS session_label, s.start_date, s.end_date,
                          co.title AS course_title
                   FROM registrations r
                   JOIN reg_customers c  ON c.id  = r.customer_id
                   JOIN reg_sessions  s  ON s.id  = r.session_id
                   JOIN reg_courses   co ON co.id = s.course_id
                   WHERE r.id=%s""",
                (reg_id,)
            )
            reg = await cur.fetchone()

    if not reg:
        raise HTTPException(404, "報名紀錄不存在")
    if not reg['email']:
        raise HTTPException(400, "客戶未填寫 email，無法發送通知")

    status = reg['reg_status']

    if status in ('data_confirmed', 'payment_submitted'):
        # 重發付款通知信（延長 token 有效期至 7 天後）
        token = reg['payment_token']
        if not token:
            raise HTTPException(409, "付款連結遺失，請重新執行「確認資料」流程")
        new_expires = datetime.now() + timedelta(days=7)
        async with get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE registrations SET payment_token_expires_at=%s WHERE id=%s",
                    (new_expires, reg_id)
                )
            await conn.commit()
        payment_url = f"{FRONTEND_URL}/#/payment/{token}"
        expire_date = new_expires.strftime("%Y/%m/%d")
        asyncio.create_task(send_payment_request(
            to_email=reg['email'], name=reg['name'],
            course_title=reg['course_title'], session_label=reg['session_label'],
            start_date=str(reg['start_date']), end_date=str(reg['end_date']),
            payment_url=payment_url, expire_date=expire_date,
        ))
        return {"ok": True, "sent": "payment"}

    if status == 'confirmed':
        asyncio.create_task(send_registration_complete(
            to_email=reg['email'], name=reg['name'],
            course_title=reg['course_title'], session_label=reg['session_label'],
            start_date=str(reg['start_date']), end_date=str(reg['end_date']),
        ))
        return {"ok": True, "sent": "complete"}

    raise HTTPException(409, f"目前狀態 {status} 不支援重發確認信")


# ── Admin: 客戶管理 ────────────────────────────────────────────

@admin_router.get("/reg/customers")
async def admin_list_customers(
    q:      Optional[str] = None,   # 搜尋：姓名 / 電話 / 身分證
    offset: int = 0,
    limit:  int = 50,
    staff = Depends(get_current_staff),
):
    """客戶列表（含報名次數統計）"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            where, params = "WHERE 1=1", []
            if q:
                where += " AND (c.name LIKE %s OR c.mobile_phone LIKE %s OR c.id_number LIKE %s)"
                like = f"%{q}%"
                params.extend([like, like, like])

            await cur.execute(f"""
                SELECT c.id, c.name, c.mobile_phone AS phone, c.email,
                       c.id_number, c.mid, c.nickname,
                       c.birth_date, c.membership_expiry,
                       COUNT(r.id)                                              AS reg_count,
                       SUM(r.reg_status = 'confirmed')                         AS confirmed_count,
                       MAX(r.registered_at)                                    AS last_reg_at
                FROM reg_customers c
                LEFT JOIN registrations r ON r.customer_id = c.id
                {where}
                GROUP BY c.id
                ORDER BY c.name
                LIMIT %s OFFSET %s
            """, params + [limit, offset])
            rows = await cur.fetchall()

            await cur.execute(f"""
                SELECT COUNT(DISTINCT c.id) AS total
                FROM reg_customers c {where}
            """, params)
            total = (await cur.fetchone())['total']

    return {
        "total": total,
        "items": [dict(r) for r in rows],
    }


@admin_router.get("/reg/customers/{customer_id}")
async def admin_get_customer(
    customer_id: int,
    staff = Depends(get_current_staff),
):
    """單一客戶完整資料 + 報名歷程"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT id, name, id_number,
                       mobile_phone AS phone, home_phone, email, mid,
                       nickname, name_en, birth_date, nationality, blood_type,
                       address, emergency_contact, emergency_phone,
                       height, weight, shoe_size, vision_left, vision_right,
                       payment_date, membership_expiry,
                       created_at, updated_at
                FROM reg_customers WHERE id=%s
            """, (customer_id,))
            customer = await cur.fetchone()
            if not customer:
                raise HTTPException(404, "客戶不存在")

            await cur.execute("""
                SELECT r.id, r.reg_status, r.payment_status,
                       r.registered_at, r.confirmed_at,
                       r.transfer_bank, r.transfer_date,
                       r.waitlist_position, r.notes,
                       s.label AS session_label, s.start_date, s.end_date,
                       co.title AS course_title, co.course_code
                FROM registrations r
                JOIN reg_sessions s  ON s.id  = r.session_id
                JOIN reg_courses  co ON co.id = s.course_id
                WHERE r.customer_id = %s
                ORDER BY r.registered_at DESC
            """, (customer_id,))
            regs = await cur.fetchall()

    return {
        "customer": dict(customer),
        "registrations": [dict(r) for r in regs],
    }
