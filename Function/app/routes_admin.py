# app/routes_admin.py  ── idiving5d-OctoFlow v260310
import json
import time
import os
import io
import zipfile
import asyncio
import httpx
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse

from app.db import get_conn
from app.auth_staff import get_current_staff, require_admin_staff
from app.security_staff_tokens import generate_admin_token, sha256_hex, token_prefix
from app.auth_password import verify_password
from pydantic import BaseModel

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_PUSH_API    = "https://api.line.me/v2/bot/message/push"
LINE_CONTENT_DIR = os.environ.get("LINE_CONTENT_DIR", "/app/data/line_content").strip() or "/app/data/line_content"
LINE_EMOJI_DIR   = os.environ.get("LINE_EMOJI_DIR",   "/app/data/line_emoji").strip()   or "/app/data/line_emoji"

_MIME_EXT = {
    "image/jpeg":   ".jpg",
    "image/png":    ".png",
    "image/gif":    ".gif",
    "image/webp":   ".webp",
    "video/mp4":    ".mp4",
    "audio/mpeg":   ".mp3",
    "audio/mp4":    ".m4a",
    "application/pdf": ".pdf",
}

router = APIRouter()
DEFAULT_AGENT_NAME = "客服"


# ── 工具函式 ─────────────────────────────────────────────────

# 透過 LINE Push API 發送純文字訊息給指定用戶或群組
async def line_push(user_id_or_group_id: str, text: str):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return (500, "LINE_CHANNEL_ACCESS_TOKEN not configured", {})
    payload = {"to": user_id_or_group_id, "messages": [{"type": "text", "text": text}]}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(LINE_PUSH_API, json=payload, headers=headers)
        return (r.status_code, r.text, payload)
    except Exception as e:
        return (500, str(e), payload)


# 清理並截斷 ticket 主旨字串至最大長度
def _normalize_subject(s: str, max_len: int = 80) -> str:
    s = (s or "").strip().replace("\n", " ")
    return " ".join(s.split())[:max_len]


# 確保指定路徑的目錄存在，不存在則遞迴建立
def _ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


# 查詢單一 ticket 詳細資訊（含 conversation 關聯）
async def _get_ticket(conn, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT t.id, t.status, t.priority, t.subject, t.opened_at, t.closed_at,
                   t.last_customer_message_at, t.updated_at, t.channel_id,
                   c.id AS conversation_id, c.channel_type, c.channel_id AS conversation_channel_id
            FROM tickets t
            JOIN conversations c ON c.id=t.conversation_id
            WHERE t.id=%s LIMIT 1
            """,
            (ticket_id,),
        )
        return await cur.fetchone()


# 查詢指定 ticket 目前 active 狀態的指派記錄
async def _get_active_assignment(conn, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, ticket_id, agent_name, status, assigned_at FROM assignments "
            "WHERE ticket_id=%s AND status='active' ORDER BY id DESC LIMIT 1",
            (ticket_id,),
        )
        return await cur.fetchone()


# 若 ticket 尚無 active 指派，自動建立新的指派記錄
async def _assign_if_needed(conn, ticket_id: int, agent_name: str):
    active = await _get_active_assignment(conn, ticket_id)
    if active:
        return active
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO assignments (ticket_id, agent_name, status, assigned_at, created_at, updated_at) "
            "VALUES (%s, %s, 'active', NOW(), NOW(), NOW())",
            (ticket_id, agent_name),
        )
    return await _get_active_assignment(conn, ticket_id)


# 將 ticket 目前 active 的指派改為 released（結案時呼叫）
async def _release_active_assignment(conn, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE assignments SET status='released', released_at=NOW(), updated_at=NOW() "
            "WHERE ticket_id=%s AND status='active'",
            (ticket_id,),
        )


# 將客服回覆的外送訊息寫入 line_events 與 messages_raw 資料表
async def _insert_outgoing_message_raw(conn, conversation_id, ticket_id, text, raw_obj, staff_id, staff_name):
    event_id = f"admin_reply_{ticket_id}_{int(time.time())}"
    event_payload = {
        "type": "message", "source": {"type": "staff"},
        "message": {"type": "text", "text": text},
        "meta": {"ticket_id": ticket_id, "conversation_id": conversation_id},
    }
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO line_events
              (event_id, event_type, source_type, user_id, conversation_id, ticket_id, event_ts, raw_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, NOW())
            ON DUPLICATE KEY UPDATE raw_json=VALUES(raw_json), event_ts=VALUES(event_ts)
            """,
            (event_id, "message", "staff", None, conversation_id, ticket_id,
             json.dumps(event_payload, ensure_ascii=False)),
        )
        await cur.execute(
            """
            INSERT INTO messages_raw
              (event_id, conversation_id, ticket_id, line_message_id,
               direction, message_type, text, raw_json, created_at,
               sender_type, sender_name, staff_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s)
            """,
            (event_id, conversation_id, ticket_id, None,
             "out", "text", text, json.dumps(raw_obj, ensure_ascii=False),
             "staff", staff_name or "客服", staff_id),
        )
        return cur.lastrowid


# 若 ticket 尚無主旨，自動取第一則客戶文字訊息作為主旨填入
async def _fill_ticket_subject_if_missing(conn, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute("SELECT subject FROM tickets WHERE id=%s LIMIT 1", (ticket_id,))
        row = await cur.fetchone()
        if not row or (row.get("subject") or "").strip():
            return
        await cur.execute(
            "SELECT text FROM messages_raw WHERE ticket_id=%s AND direction='in' "
            "AND message_type='text' AND text IS NOT NULL AND text <> '' ORDER BY id ASC LIMIT 1",
            (ticket_id,),
        )
        r2 = await cur.fetchone()
        first_text = ((r2.get("text") if r2 else "") or "").strip()
        if first_text:
            await cur.execute(
                "UPDATE tickets SET subject=%s, updated_at=NOW() WHERE id=%s",
                (_normalize_subject(first_text), ticket_id)
            )


# 客服回覆後將 ticket 狀態更新為 pending 並刷新更新時間
async def _touch_after_reply(conn, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE tickets SET status='pending', updated_at=NOW() WHERE id=%s AND status='open'",
            (ticket_id,),
        )
        await cur.execute("UPDATE tickets SET updated_at=NOW() WHERE id=%s", (ticket_id,))


# 從 LINE API 下載指定訊息的媒體內容，回傳二進位資料與 MIME 類型
async def _fetch_line_content(message_id: str) -> tuple[bytes, str]:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN not set")
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"})
    if r.status_code != 200:
        raise RuntimeError(f"LINE content fetch failed {r.status_code}: {r.text}")
    mime = (r.headers.get("content-type") or "").split(";")[0].strip() or "application/octet-stream"
    return r.content, mime


# 非同步包裝：在 executor 中執行同步的 LINE emoji 下載與 zip 解析
async def _fetch_line_emoji(product_id: str, emoji_id: str) -> tuple[bytes, str]:
    """在 executor 裡跑同步的 zip 解析，避免阻塞 event loop"""
    return await asyncio.get_event_loop().run_in_executor(
        None, _fetch_line_emoji_sync, product_id, emoji_id
    )


# 同步下載 LINE emoji 圖片（先嘗試直連，失敗再下載 package.zip 解壓縮）
def _fetch_line_emoji_sync(product_id: str, emoji_id: str) -> tuple[bytes, str]:
    import requests
    direct_candidates = [
        f"https://stickershop.line-scdn.net/sticonshop/v1/sticon/{product_id}/iPhone/{emoji_id}.png",
        f"https://stickershop.line-scdn.net/sticonshop/v1/sticon/{product_id}/iPhone/{emoji_id}.webp",
    ]
    for url in direct_candidates:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.content:
            mime = (r.headers.get("Content-Type") or "").split(";")[0].strip() or "image/png"
            return r.content, mime

    zip_url = f"https://stickershop.line-scdn.net/sticonshop/v1/{product_id}/sticon/iphone/package.zip"
    zr = requests.get(zip_url, timeout=30)
    if zr.status_code != 200:
        raise RuntimeError(f"emoji zip fetch failed {zr.status_code}")

    zf = zipfile.ZipFile(io.BytesIO(zr.content))
    targets = []
    for name in zf.namelist():
        base = os.path.basename(name)
        if base.startswith(str(emoji_id)) and base.endswith((".png", ".webp", ".gif")):
            targets.append(name)
    if not targets:
        eid3 = str(emoji_id).zfill(3)
        for name in zf.namelist():
            base = os.path.basename(name)
            if base.startswith(eid3) and base.endswith((".png", ".webp", ".gif")):
                targets.append(name)
    if not targets:
        raise RuntimeError("emoji file not found in package.zip")

    def _score(n: str) -> int:
        b = n.lower()
        return 0 if b.endswith(".png") else (1 if b.endswith(".webp") else 2)

    targets.sort(key=_score)
    pick = targets[0]
    data = zf.read(pick)
    if pick.lower().endswith(".webp"): return data, "image/webp"
    if pick.lower().endswith(".gif"):  return data, "image/gif"
    return data, "image/png"


# 依 ticket_id 查詢對應客戶的 customer_id（支援 user/group/room 三種 channel 類型）
async def _get_customer_id_by_ticket(conn, ticket_id: int) -> int | None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT COALESCE(cu_direct.id, cu_sender.id) AS customer_id
            FROM tickets t
            JOIN conversations c ON c.id = t.conversation_id
            LEFT JOIN customers cu_direct ON cu_direct.line_user_id = c.channel_id
                                          AND c.channel_type = 'user'
            LEFT JOIN customers cu_sender ON cu_sender.line_user_id = c.channel_id
                                          AND c.channel_type IN ('group', 'room')
            WHERE t.id = %s LIMIT 1
            """,
            (ticket_id,),
        )
        row = await cur.fetchone()
        return row.get("customer_id") if row else None


# ── Pydantic Models ──────────────────────────────────────────

class ReplyBody(BaseModel):
    text: str
    agent_name: str | None = None
    note: str | None = None

class CloseBody(BaseModel):
    note: str | None = None

class TokenCreateBody(BaseModel):
    staff_id: int
    label: str | None = None

class TokenRevokeBody(BaseModel):
    token_id: int

class NoteCreateBody(BaseModel):
    note: str

class NoteUpdateBody(BaseModel):
    note: str

class StaffCreateBody(BaseModel):
    name: str
    username: str
    password: str
    role: str = "staff"   # "admin" | "staff"

class StaffUpdateBody(BaseModel):
    name: str | None = None
    username: str | None = None
    role: str | None = None
    is_active: int | None = None   # 1 啟用 / 0 停用

class StaffSetPasswordBody(BaseModel):
    password: str

class CustomerNameBody(BaseModel):
    customer_name: str | None = None


# ── Endpoints ────────────────────────────────────────────────

# 列出 ticket 清單，支援狀態篩選、分頁，並可自動補齊 ticket 主旨
@router.get("/tickets")
async def list_tickets(
    staff: dict = Depends(get_current_staff),
    status: str = Query(default="open,pending"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    autofill_subject: bool = Query(default=True),
):
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()] or ["open", "pending"]
    placeholders = ",".join(["%s"] * len(statuses))

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                  t.id AS ticket_id, t.status, t.current_status, t.priority, t.subject,
                  t.opened_at, t.closed_at, t.last_customer_message_at,
                  c.id AS conversation_id, c.channel_type, c.channel_id, c.last_event_at, c.last_message_at,
                  COALESCE(cu_direct.id,            cu_sender.id)            AS customer_id,
                  COALESCE(cu_direct.display_name,  cu_sender.display_name, lc.display_name) AS display_name,
                  COALESCE(cu_direct.customer_name, cu_sender.customer_name, lc.custom_name)  AS customer_name,
                  COALESCE(cu_direct.picture_url,   cu_sender.picture_url,  lc.picture_url)  AS picture_url,
                  COALESCE(cu_direct.phone,         cu_sender.phone)         AS phone,
                  a.agent_name AS active_agent, a.assigned_at,
                  (SELECT mr.text FROM messages_raw mr
                   WHERE mr.ticket_id=t.id AND mr.direction='in' AND mr.message_type='text'
                     AND mr.text IS NOT NULL AND mr.text <> ''
                   ORDER BY mr.id ASC LIMIT 1) AS first_in_text,
                  (SELECT mr2.text FROM messages_raw mr2
                   WHERE mr2.ticket_id=t.id AND mr2.message_type='text'
                     AND mr2.text IS NOT NULL AND mr2.text <> ''
                   ORDER BY mr2.id DESC LIMIT 1) AS last_text
                FROM tickets t
                JOIN conversations c ON c.id=t.conversation_id
                LEFT JOIN customers cu_direct ON cu_direct.line_user_id=c.channel_id
                                              AND c.channel_type='user'
                LEFT JOIN customers cu_sender ON cu_sender.line_user_id=c.channel_id
                                              AND c.channel_type IN ('group','room')
                LEFT JOIN line_channels lc ON lc.channel_id=c.channel_id
                                          AND c.channel_type IN ('group','room')
                LEFT JOIN assignments a ON a.ticket_id=t.id AND a.status='active'
                WHERE t.status IN ({placeholders})
                ORDER BY COALESCE(t.last_customer_message_at, c.last_message_at, t.opened_at) DESC
                LIMIT %s OFFSET %s
                """.format(placeholders=placeholders),
                (*statuses, limit, offset),
            )
            rows = await cur.fetchall()

            if autofill_subject:
                for r in rows:
                    if not (r.get("subject") or "").strip():
                        first_text = (r.get("first_in_text") or "").strip()
                        if first_text:
                            new_subj = _normalize_subject(first_text)
                            await cur.execute(
                                "UPDATE tickets SET subject=%s, updated_at=NOW() WHERE id=%s",
                                (new_subj, r["ticket_id"])
                            )
                            r["subject"] = new_subj

            # 批量載入客戶標籤
            customer_ids = list({r["customer_id"] for r in rows if r.get("customer_id")})
            tags_map: dict[int, list] = {}
            if customer_ids:
                ph = ",".join(["%s"] * len(customer_ids))
                await cur.execute(
                    f"""
                    SELECT ctm.customer_id, t.id, t.name, t.color
                    FROM customer_tag_map ctm
                    JOIN tags t ON ctm.tag_id = t.id
                    WHERE ctm.customer_id IN ({ph})
                    ORDER BY t.name
                    """,
                    customer_ids,
                )
                for tr in await cur.fetchall():
                    cid = tr["customer_id"]
                    tags_map.setdefault(cid, []).append(
                        {"id": tr["id"], "name": tr["name"], "color": tr["color"]}
                    )
            for r in rows:
                r["tags"] = tags_map.get(r.get("customer_id"), [])

        await conn.commit()
        return {"ok": True, "items": rows, "limit": limit, "offset": offset}


# 取得指定 ticket 的訊息記錄清單（含媒體、貼圖等所有類型）
@router.get("/tickets/{ticket_id}/messages")
async def get_ticket_messages(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=200, ge=1, le=500),
):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, conversation_id, ticket_id, direction, message_type, text,
                       content_path, content_mime, content_size, content_name, content_url,
                       sticker_id, package_id, sticker_resource_type, sticker_url,
                       sender_type, sender_name, sender_picture_url, staff_id, created_at
                FROM messages_raw WHERE ticket_id=%s ORDER BY id LIMIT %s
                """,
                (ticket_id, limit),
            )
            rows = await cur.fetchall()
        return {"ok": True, "items": rows}


# 客服回覆指定 ticket：透過 LINE Push 傳送訊息並記錄到資料庫
@router.post("/tickets/{ticket_id}/reply")
async def reply_ticket(ticket_id: int, body: ReplyBody, staff: dict = Depends(get_current_staff)):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    agent_name = (body.agent_name or DEFAULT_AGENT_NAME).strip()
    staff_id   = int(staff.get("staff_id"))
    staff_name = (staff.get("name") or "客服").strip()

    async with get_conn() as conn:
        ticket = await _get_ticket(conn, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="ticket not found")

        channel_id = (ticket.get("channel_id") or "").strip() or (ticket.get("conversation_channel_id") or "").strip()
        if not channel_id:
            raise HTTPException(status_code=400, detail="ticket has no channel_id")

        await _assign_if_needed(conn, ticket_id, agent_name)
        code, body_text, payload = await line_push(channel_id, text)

        raw_obj = {"line_push_status": code, "line_push_body": body_text, "payload": payload,
                   "note": body.note, "agent_name": agent_name, "staff_id": staff_id, "staff_name": staff_name}

        await _insert_outgoing_message_raw(conn, int(ticket["conversation_id"]), ticket_id, text, raw_obj, staff_id, staff_name)
        await _fill_ticket_subject_if_missing(conn, ticket_id)
        await _touch_after_reply(conn, ticket_id)
        await conn.commit()

        result: dict = {"ok": True, "line_status": code}
        if code != 200:
            result["line_warning"] = f"訊息已儲存，但 LINE 推播失敗（{code}）─ 客人可能已封鎖或移除 LINE@"
        return result


# 關閉指定 ticket，並釋放目前的指派客服
@router.post("/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: int, body: CloseBody, staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        ticket = await _get_ticket(conn, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="ticket not found")
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE tickets SET status='closed', closed_at=NOW(), updated_at=NOW() "
                "WHERE id=%s AND status <> 'closed'",
                (ticket_id,),
            )
        await _release_active_assignment(conn, ticket_id)
        await conn.commit()
        return {"ok": True, "note": body.note}


# 帳號密碼登入：驗證後產生 Token 並回傳
class PasswordLoginBody(BaseModel):
    username: str
    password: str

@router.post("/auth/login")
async def auth_login(body: PasswordLoginBody):
    username = (body.username or "").strip()
    password = (body.password or "").strip()
    if not username or not password:
        raise HTTPException(status_code=400, detail="username / password 不可空白")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, name, role, password_hash, is_active
                FROM staff
                WHERE username=%s
                LIMIT 1
                """,
                (username,),
            )
            row = await cur.fetchone()

    if not row or not row.get("is_active"):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    if not row.get("password_hash"):
        raise HTTPException(status_code=401, detail="此帳號尚未設定密碼，請聯絡管理員")

    if not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    # 驗證通過：產生新 Token
    raw = generate_admin_token()
    th  = sha256_hex(raw)
    tp  = token_prefix(raw)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO staff_tokens (staff_id, token_hash, token_prefix, label) VALUES (%s, %s, %s, %s)",
                (int(row["id"]), th, tp, "password-login"),
            )
        await conn.commit()

    return {
        "ok":   True,
        "token": raw,
        "name": row["name"],
        "role": row["role"],
    }


# 登出：撤銷目前使用的 Token
@router.post("/auth/logout")
async def auth_logout(staff: dict = Depends(get_current_staff)):
    token_id = staff.get("token_id")
    if token_id:
        async with get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE staff_tokens SET revoked_at=NOW() WHERE id=%s AND revoked_at IS NULL",
                    (int(token_id),),
                )
            await conn.commit()
    return {"ok": True}


# 取得目前登入員工的基本資料（依 Token 識別）
@router.get("/staff/me")
async def staff_me(staff: dict = Depends(get_current_staff)):
    return {"ok": True, "staff": staff}


# 列出所有員工帳號（admin only）
@router.get("/staff")
async def staff_list(staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, name, username, role, is_active, created_at FROM staff ORDER BY id ASC"
            )
            rows = await cur.fetchall()
    return {"ok": True, "items": rows}


# 新增員工帳號（admin only）
@router.post("/staff")
async def staff_create(body: StaffCreateBody, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    name     = (body.name or "").strip()
    username = (body.username or "").strip()
    password = (body.password or "").strip()
    role     = body.role if body.role in ("admin", "staff") else "staff"
    if not name or not username or not password:
        raise HTTPException(status_code=400, detail="name / username / password 不可空白")

    from app.auth_password import hash_password
    pw_hash = hash_password(password)

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    "INSERT INTO staff (name, username, password_hash, role, is_active) VALUES (%s, %s, %s, %s, 1)",
                    (name, username, pw_hash, role),
                )
                new_id = cur.lastrowid
            except Exception as e:
                if "Duplicate" in str(e):
                    raise HTTPException(status_code=409, detail="帳號已存在")
                raise
        await conn.commit()
    return {"ok": True, "id": new_id}


# 更新員工資料（name / username / role / is_active），admin only
@router.patch("/staff/{staff_id}")
async def staff_update(staff_id: int, body: StaffUpdateBody, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    fields, values = [], []
    if body.name is not None:
        fields.append("name=%s");       values.append(body.name.strip())
    if body.username is not None:
        fields.append("username=%s");   values.append(body.username.strip())
    if body.role is not None and body.role in ("admin", "staff"):
        fields.append("role=%s");       values.append(body.role)
    if body.is_active is not None:
        fields.append("is_active=%s");  values.append(int(body.is_active))
    if not fields:
        raise HTTPException(status_code=400, detail="沒有要更新的欄位")
    values.append(staff_id)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(f"UPDATE staff SET {', '.join(fields)} WHERE id=%s", values)
            except Exception as e:
                if "Duplicate" in str(e):
                    raise HTTPException(status_code=409, detail="帳號已存在")
                raise
        await conn.commit()
    return {"ok": True}


# 重設指定員工的登入密碼（admin only）
@router.post("/staff/{staff_id}/set-password")
async def staff_set_password(staff_id: int, body: StaffSetPasswordBody, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    password = (body.password or "").strip()
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密碼至少 6 個字元")
    from app.auth_password import hash_password
    pw_hash = hash_password(password)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE staff SET password_hash=%s WHERE id=%s",
                (pw_hash, staff_id),
            )
        await conn.commit()
    return {"ok": True}


# 刪除員工帳號（admin only）
@router.delete("/staff/{staff_id}")
async def staff_delete(staff_id: int, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    me_id = int(staff.get("staff_id"))
    if staff_id == me_id:
        raise HTTPException(status_code=400, detail="無法刪除自己的帳號")
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM staff_tokens WHERE staff_id=%s", (staff_id,))
            await cur.execute("DELETE FROM staff WHERE id=%s", (staff_id,))
        await conn.commit()
    return {"ok": True}


# 統計指定天數內客戶常問的問題短語與出現次數（admin only）
@router.get("/stats/questions")
async def stats_questions(
    response: Response,
    staff: dict = Depends(get_current_staff),
    days: int = Query(default=7, ge=1, le=60),
    limit: int = Query(default=2000, ge=10, le=20000),
):
    require_admin_staff(staff)
    response.headers["Cache-Control"] = "no-store"
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT text AS phrase, COUNT(*) AS count
                FROM messages_raw
                WHERE direction='in' AND message_type='text'
                  AND created_at >= (NOW() - INTERVAL %s DAY)
                  AND text IS NOT NULL AND text <> ''
                GROUP BY text
                ORDER BY count DESC
                LIMIT %s
                """,
                (days, limit),
            )
            rows = await cur.fetchall()
    items = [{"phrase": r["phrase"], "count": r["count"]} for r in rows]
    return {"ok": True, "days": days, "limit": limit, "items": items}


# 為指定員工建立新的管理員 Token（admin only）
@router.post("/staff/tokens/create")
async def staff_token_create(body: TokenCreateBody, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    if body.staff_id <= 0:
        raise HTTPException(status_code=400, detail="staff_id required")
    raw = generate_admin_token()
    th  = sha256_hex(raw)
    tp  = token_prefix(raw)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO staff_tokens (staff_id, token_hash, token_prefix, label) VALUES (%s, %s, %s, %s)",
                (int(body.staff_id), th, tp, body.label or None),
            )
            token_id = cur.lastrowid
        await conn.commit()
        return {"ok": True, "token_id": token_id, "token": raw, "token_prefix": tp}


# 撤銷指定的員工 Token，使其立即失效（admin only）
@router.post("/staff/tokens/revoke")
async def staff_token_revoke(body: TokenRevokeBody, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    if body.token_id <= 0:
        raise HTTPException(status_code=400, detail="token_id required")
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE staff_tokens SET revoked_at=NOW() WHERE id=%s AND revoked_at IS NULL",
                (int(body.token_id),),
            )
        await conn.commit()
        return {"ok": True}


# 列出指定員工的所有 Token（admin 可查任何人，一般員工只能查自己）
@router.get("/staff/{staff_id}/tokens")
async def staff_tokens_list(staff_id: int, staff: dict = Depends(get_current_staff)):
    me_staff_id = int(staff["staff_id"])
    if staff.get("role") != "admin" and staff_id != me_staff_id:
        raise HTTPException(status_code=403, detail="forbidden")
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, token_prefix, label, created_at, last_used_at, revoked_at "
                "FROM staff_tokens WHERE staff_id=%s ORDER BY id DESC",
                (staff_id,),
            )
            rows = await cur.fetchall()
        return {"ok": True, "items": rows}


# 取得指定 LINE 訊息的媒體內容，本地無檔案則自動從 LINE API 重新下載
@router.get("/content/{line_message_id}")
async def get_content(line_message_id: str, staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, content_path, content_mime, content_name FROM messages_raw "
                "WHERE line_message_id=%s LIMIT 1",
                (line_message_id,),
            )
            row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="content not found")

        need_download = not row.get("content_path") or not os.path.exists(row["content_path"])
        if need_download:
            try:
                data, mime = await _fetch_line_content(line_message_id)
                _ensure_dir(LINE_CONTENT_DIR)
                ext   = _MIME_EXT.get(mime, "")
                fname = f"{line_message_id}{ext}"
                fpath = os.path.join(LINE_CONTENT_DIR, fname)
                with open(fpath, "wb") as f:
                    f.write(data)
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE messages_raw SET content_path=%s, content_mime=%s, content_size=%s, "
                        "content_name=%s, content_url=%s WHERE id=%s",
                        (fpath, mime, len(data), fname, f"/admin/api/content/{line_message_id}", row["id"]),
                    )
                await conn.commit()
                row["content_path"] = fpath
                row["content_mime"]  = mime
                row["content_name"]  = fname
            except Exception as e:
                raise HTTPException(status_code=404, detail=f"content not available: {e}")

    return FileResponse(
        row["content_path"],
        media_type=row.get("content_mime") or "application/octet-stream",
        filename=row.get("content_name") or None,
    )


# 取得 LINE emoji 圖片，優先使用本地快取，無則從 LINE CDN 下載並儲存
@router.get("/emoji/{product_id}/{emoji_id}")
async def get_emoji(product_id: str, emoji_id: str, staff: dict = Depends(get_current_staff)):
    safe_product = product_id.replace("/", "_").strip()
    safe_emoji   = emoji_id.replace("/", "_").strip()
    folder = os.path.join(LINE_EMOJI_DIR, safe_product)
    _ensure_dir(folder)

    for ext, mime in [(".png", "image/png"), (".webp", "image/webp"), (".gif", "image/gif")]:
        fpath = os.path.join(folder, f"{safe_emoji}{ext}")
        if os.path.exists(fpath):
            return FileResponse(fpath, media_type=mime, filename=os.path.basename(fpath),
                                headers={"Cache-Control": "public, max-age=31536000, immutable"})

    try:
        data, mime = await _fetch_line_emoji(safe_product, safe_emoji)
        ext = ".webp" if mime == "image/webp" else (".gif" if mime == "image/gif" else ".png")
        fpath = os.path.join(folder, f"{safe_emoji}{ext}")
        with open(fpath, "wb") as f:
            f.write(data)
        return FileResponse(fpath, media_type=mime, filename=os.path.basename(fpath),
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fetch emoji failed: {e}")


# ── Customer Notes ────────────────────────────────────────────

# 列出指定 ticket 對應客戶的所有備忘錄
@router.get("/tickets/{ticket_id}/notes")
async def list_ticket_notes(ticket_id: int, staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        # 取得 conversation channel 資訊
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT c.channel_type, c.channel_id,
                       COALESCE(cu_direct.id, cu_sender.id) AS customer_id
                FROM tickets t
                JOIN conversations c ON c.id = t.conversation_id
                LEFT JOIN customers cu_direct ON cu_direct.line_user_id = c.channel_id
                                              AND c.channel_type = 'user'
                LEFT JOIN customers cu_sender ON cu_sender.line_user_id = c.channel_id
                                              AND c.channel_type IN ('group', 'room')
                WHERE t.id = %s LIMIT 1
                """,
                (ticket_id,),
            )
            ch = await cur.fetchone()

        if not ch:
            return {"ok": True, "customer_id": None, "customer_name": None, "items": []}

        customer_id  = ch.get("customer_id")
        channel_type = ch.get("channel_type")
        channel_id   = ch.get("channel_id")

        async with conn.cursor() as cur:
            # 取得自訂名稱
            if customer_id:
                await cur.execute("SELECT customer_name FROM customers WHERE id = %s", (customer_id,))
                cu_row = await cur.fetchone()
                customer_name = cu_row.get("customer_name") if cu_row else None
            elif channel_type in ("group", "room"):
                await cur.execute("SELECT custom_name FROM line_channels WHERE channel_id = %s", (channel_id,))
                lc_row = await cur.fetchone()
                customer_name = lc_row.get("custom_name") if lc_row else None
            else:
                customer_name = None

            # 取得備忘錄（僅限有 customer_id 時）
            rows = []
            if customer_id:
                await cur.execute(
                    "SELECT id, customer_id, staff_id, staff_name, note, created_at, updated_at "
                    "FROM customer_notes WHERE customer_id = %s ORDER BY id DESC",
                    (customer_id,),
                )
                rows = await cur.fetchall()

        return {
            "ok": True,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "channel_type": channel_type,
            "items": rows,
        }


# 為指定 ticket 的客戶新增一筆備忘錄
@router.post("/tickets/{ticket_id}/notes")
async def create_ticket_note(ticket_id: int, body: NoteCreateBody, staff: dict = Depends(get_current_staff)):
    note_text = (body.note or "").strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="note is required")

    staff_id   = int(staff.get("staff_id"))
    staff_name = (staff.get("name") or "客服").strip()

    async with get_conn() as conn:
        customer_id = await _get_customer_id_by_ticket(conn, ticket_id)
        if not customer_id:
            raise HTTPException(status_code=404, detail="customer not found for this ticket")
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO customer_notes (customer_id, staff_id, staff_name, note, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, NOW(), NOW())",
                (customer_id, staff_id, staff_name, note_text),
            )
            note_id = cur.lastrowid
        await conn.commit()
        return {"ok": True, "note_id": note_id, "customer_id": customer_id}


# 更新指定備忘錄內容（admin 可編輯任何人的，一般員工只能編輯自己的）
@router.put("/tickets/{ticket_id}/notes/{note_id}")
async def update_ticket_note(ticket_id: int, note_id: int, body: NoteUpdateBody, staff: dict = Depends(get_current_staff)):
    note_text = (body.note or "").strip()
    if not note_text:
        raise HTTPException(status_code=400, detail="note is required")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            if staff.get("role") == "admin":
                await cur.execute(
                    "UPDATE customer_notes SET note=%s, updated_at=NOW() WHERE id=%s",
                    (note_text, note_id),
                )
            else:
                await cur.execute(
                    "UPDATE customer_notes SET note=%s, updated_at=NOW() WHERE id=%s AND staff_id=%s",
                    (note_text, note_id, int(staff.get("staff_id"))),
                )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="note not found or permission denied")
        await conn.commit()
        return {"ok": True}


# 刪除指定備忘錄（admin 可刪任何人的，一般員工只能刪自己的）
@router.delete("/tickets/{ticket_id}/notes/{note_id}")
async def delete_ticket_note(ticket_id: int, note_id: int, staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            if staff.get("role") == "admin":
                await cur.execute("DELETE FROM customer_notes WHERE id=%s", (note_id,))
            else:
                await cur.execute(
                    "DELETE FROM customer_notes WHERE id=%s AND staff_id=%s",
                    (note_id, int(staff.get("staff_id"))),
                )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="note not found or permission denied")
        await conn.commit()
        return {"ok": True}


# ── Profile 補齊 ──────────────────────────────────────────────

# 從 LINE API 取得指定用戶的個人資料（displayName、pictureUrl）
async def _fetch_line_user_profile(user_id: str) -> dict | None:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://api.line.me/v2/bot/profile/{user_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            )
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# 批次同步客戶 LINE 個人資料（顯示名稱與頭貼），admin only
@router.post("/customers/sync_profiles")
async def sync_customer_profiles(
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=50, ge=1, le=200),
    force: bool = Query(default=False, description="force=true 強制重抓所有人，包含已有資料者"),
):
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            if force:
                await cur.execute(
                    """
                    SELECT id, line_user_id FROM customers
                    WHERE line_user_id IS NOT NULL
                      AND line_user_id NOT LIKE 'C%%'
                      AND line_user_id NOT LIKE 'R%%'
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            else:
                await cur.execute(
                    """
                    SELECT id, line_user_id FROM customers
                    WHERE (display_name IS NULL OR picture_url IS NULL)
                      AND line_user_id IS NOT NULL
                      AND line_user_id NOT LIKE 'C%%'
                      AND line_user_id NOT LIKE 'R%%'
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = await cur.fetchall()

        updated = failed = skipped = 0
        for row in rows:
            profile = await _fetch_line_user_profile(row["line_user_id"])
            if not profile:
                failed += 1
                continue
            dname = (profile.get("displayName") or "").strip() or None
            pic   = (profile.get("pictureUrl")  or "").strip() or None
            if not dname and not pic:
                skipped += 1
                continue
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE customers SET display_name=%s, picture_url=%s, updated_at=NOW() WHERE id=%s"
                    if force else
                    "UPDATE customers SET display_name=COALESCE(%s, display_name), "
                    "picture_url=COALESCE(%s, picture_url), updated_at=NOW() WHERE id=%s",
                    (dname, pic, row["id"]),
                )
            updated += 1

        await conn.commit()
        return {"ok": True, "updated": updated, "failed": failed, "skipped": skipped, "total": len(rows)}


# 從 LINE API 取得群組摘要（groupName、pictureUrl）
async def _fetch_line_group_summary(group_id: str) -> dict | None:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"https://api.line.me/v2/bot/group/{group_id}/summary",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            )
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# 批次同步 LINE 群組名稱與圖片至 line_channels 資料表，admin only
@router.post("/channels/sync_groups")
async def sync_group_channels(
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=50, ge=1, le=200),
    force: bool = Query(default=False, description="force=true 強制重抓所有群組，包含已有名稱者"),
):
    """從 line_channels 中撈出群組 channel，重新從 LINE API 拉取 groupName / pictureUrl"""
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            if force:
                await cur.execute(
                    """
                    SELECT channel_id FROM line_channels
                    WHERE channel_type='group'
                    ORDER BY updated_at ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
            else:
                await cur.execute(
                    """
                    SELECT channel_id FROM line_channels
                    WHERE channel_type='group'
                      AND (display_name IS NULL OR picture_url IS NULL)
                    ORDER BY updated_at ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = await cur.fetchall()

        # 也撈 conversations 裡有 group 但 line_channels 尚未建立的
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT c.channel_id FROM conversations c
                LEFT JOIN line_channels lc ON lc.channel_id=c.channel_id AND lc.channel_type='group'
                WHERE c.channel_type='group'
                  AND lc.channel_id IS NULL
                LIMIT %s
                """,
                (limit,),
            )
            missing_rows = await cur.fetchall()

        all_group_ids = list({r["channel_id"] for r in rows} | {r["channel_id"] for r in missing_rows})

        updated = failed = skipped = 0
        for group_id in all_group_ids:
            summary = await _fetch_line_group_summary(group_id)
            if not summary:
                failed += 1
                continue
            gname = (summary.get("groupName") or "").strip() or None
            pic   = (summary.get("pictureUrl") or "").strip() or None
            if not gname and not pic:
                skipped += 1
                continue
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO line_channels (channel_type, channel_id, display_name, picture_url, updated_at)
                    VALUES ('group', %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        display_name = VALUES(display_name),
                        picture_url  = VALUES(picture_url),
                        updated_at   = NOW()
                    """,
                    (group_id, gname, pic),
                )
            updated += 1

        await conn.commit()
        return {"ok": True, "updated": updated, "failed": failed, "skipped": skipped, "total": len(all_group_ids)}


# 查詢客戶個人資料完整度統計（總數、缺少資料數、已有資料數）
@router.get("/customers/profile_stats")
async def customer_profile_stats(staff: dict = Depends(get_current_staff)):
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) AS total FROM customers")
            total = (await cur.fetchone())["total"]
            await cur.execute(
                "SELECT COUNT(*) AS c FROM customers WHERE display_name IS NULL OR picture_url IS NULL"
            )
            missing = (await cur.fetchone())["c"]
        return {"ok": True, "total": total, "missing_profile": missing, "has_profile": total - missing}


# 更新工單對應客戶或群組的自訂名稱（統一入口）
@router.patch("/tickets/{ticket_id}/custom_name")
async def update_ticket_custom_name(
    ticket_id: int,
    body: CustomerNameBody,
    staff: dict = Depends(get_current_staff),
):
    name = (body.customer_name or "").strip() or None
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT c.channel_type, c.channel_id,
                       COALESCE(cu_direct.id, cu_sender.id) AS customer_id
                FROM tickets t
                JOIN conversations c ON c.id = t.conversation_id
                LEFT JOIN customers cu_direct ON cu_direct.line_user_id = c.channel_id
                                              AND c.channel_type = 'user'
                LEFT JOIN customers cu_sender ON cu_sender.line_user_id = c.channel_id
                                              AND c.channel_type IN ('group', 'room')
                WHERE t.id = %s LIMIT 1
                """,
                (ticket_id,),
            )
            ch = await cur.fetchone()

        if not ch:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="ticket not found")

        channel_type = ch.get("channel_type")
        channel_id   = ch.get("channel_id")
        customer_id  = ch.get("customer_id")

        async with conn.cursor() as cur:
            if customer_id:
                await cur.execute(
                    "UPDATE customers SET customer_name=%s, updated_at=NOW() WHERE id=%s",
                    (name, customer_id),
                )
            elif channel_type in ("group", "room"):
                await cur.execute(
                    "UPDATE line_channels SET custom_name=%s, updated_at=NOW() WHERE channel_id=%s",
                    (name, channel_id),
                )
        await conn.commit()
    return {"ok": True, "customer_name": name}


# 更新客戶自訂名稱
@router.patch("/customers/{customer_id}/name")
async def update_customer_name(
    customer_id: int,
    body: CustomerNameBody,
    staff: dict = Depends(get_current_staff),
):
    name = (body.customer_name or "").strip() or None
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE customers SET customer_name=%s, updated_at=NOW() WHERE id=%s",
                (name, customer_id),
            )
            if cur.rowcount == 0:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="customer not found")
        await conn.commit()
    return {"ok": True, "customer_name": name}
