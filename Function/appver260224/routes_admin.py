# app/routes_admin.py
# ============================================================
# 修改清單：
#   1. 移除重複的 get_emoji endpoint（原本有兩個）
#   2. 移除本地 get_conn()，改從 app.db import
# ============================================================
import json
import time
import os
import io
import zipfile
import requests
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.db import get_conn                                          # ← 改這裡
from app.auth_staff import get_current_staff, require_admin_staff
from app.security_staff_tokens import generate_admin_token, sha256_hex, token_prefix
from pydantic import BaseModel

# LINE 設定
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
LINE_PUSH_API   = "https://api.line.me/v2/bot/message/push"
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


# ── 工具函式 ────────────────────────────────────────────────

def line_push(user_id_or_group_id: str, text: str):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return (500, "LINE_CHANNEL_ACCESS_TOKEN not configured", {})
    payload = {"to": user_id_or_group_id, "messages": [{"type": "text", "text": text}]}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
    try:
        r = requests.post(LINE_PUSH_API, json=payload, headers=headers, timeout=10)
        return (r.status_code, r.text, payload)
    except Exception as e:
        return (500, str(e), payload)


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_subject(s: str, max_len: int = 80) -> str:
    s = (s or "").strip().replace("\n", " ")
    return " ".join(s.split())[:max_len]


def _ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def _get_ticket(conn, ticket_id: int):
    with conn.cursor() as cur:
        cur.execute(
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
        return cur.fetchone()


def _get_active_assignment(conn, ticket_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, ticket_id, agent_name, status, assigned_at FROM assignments "
            "WHERE ticket_id=%s AND status='active' ORDER BY id DESC LIMIT 1",
            (ticket_id,),
        )
        return cur.fetchone()


def _assign_if_needed(conn, ticket_id: int, agent_name: str):
    active = _get_active_assignment(conn, ticket_id)
    if active:
        return active
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO assignments (ticket_id, agent_name, status, assigned_at, created_at, updated_at) "
            "VALUES (%s, %s, 'active', NOW(), NOW(), NOW())",
            (ticket_id, agent_name),
        )
    return _get_active_assignment(conn, ticket_id)


def _release_active_assignment(conn, ticket_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE assignments SET status='released', released_at=NOW(), updated_at=NOW() "
            "WHERE ticket_id=%s AND status='active'",
            (ticket_id,),
        )


def _insert_outgoing_message_raw(conn, conversation_id, ticket_id, text, raw_obj, staff_id, staff_name):
    event_id = f"admin_reply_{ticket_id}_{int(time.time())}"
    event_payload = {
        "type": "message", "source": {"type": "staff"},
        "message": {"type": "text", "text": text},
        "meta": {"ticket_id": ticket_id, "conversation_id": conversation_id},
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO line_events
              (event_id, event_type, source_type, user_id, conversation_id, ticket_id, event_ts, raw_json, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s, NOW())
            ON DUPLICATE KEY UPDATE raw_json=VALUES(raw_json), event_ts=VALUES(event_ts)
            """,
            (event_id, "message", "staff", None, conversation_id, ticket_id,
             json.dumps(event_payload, ensure_ascii=False)),
        )
        cur.execute("SELECT COUNT(*) AS c FROM line_events WHERE event_id=%s", (event_id,))
        chk = cur.fetchone()
        if not chk or int(chk.get("c", 0)) != 1:
            raise RuntimeError(f"line_events insert failed, event_id={event_id}")

        cur.execute(
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


def _fill_ticket_subject_if_missing(conn, ticket_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT subject FROM tickets WHERE id=%s LIMIT 1", (ticket_id,))
        row = cur.fetchone()
        if not row or (row.get("subject") or "").strip():
            return
        cur.execute(
            "SELECT text FROM messages_raw WHERE ticket_id=%s AND direction='in' "
            "AND message_type='text' AND text IS NOT NULL AND text <> '' ORDER BY id ASC LIMIT 1",
            (ticket_id,),
        )
        r2 = cur.fetchone()
        first_text = ((r2.get("text") if r2 else "") or "").strip()
        if first_text:
            cur.execute("UPDATE tickets SET subject=%s, updated_at=NOW() WHERE id=%s",
                        (_normalize_subject(first_text), ticket_id))


def _touch_after_reply(conn, ticket_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tickets SET status='pending', updated_at=NOW() WHERE id=%s AND status='open'",
            (ticket_id,),
        )
        cur.execute("UPDATE tickets SET updated_at=NOW() WHERE id=%s", (ticket_id,))


def _fetch_line_content(message_id: str) -> tuple[bytes, str]:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN not set")
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    r = requests.get(url, headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"LINE content fetch failed {r.status_code}: {r.text}")
    mime = (r.headers.get("Content-Type") or "").split(";")[0].strip() or "application/octet-stream"
    return r.content, mime


def _fetch_line_emoji(product_id: str, emoji_id: str) -> tuple[bytes, str]:
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


# ── Pydantic Models ─────────────────────────────────────────

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


# ── Endpoints ───────────────────────────────────────────────

@router.get("/tickets")
def list_tickets(
    staff: dict = Depends(get_current_staff),
    status: str = Query(default="open,pending"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    autofill_subject: bool = Query(default=True),
):
    statuses = [s.strip() for s in (status or "").split(",") if s.strip()] or ["open", "pending"]
    placeholders = ",".join(["%s"] * len(statuses))

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  t.id AS ticket_id, t.status, t.priority, t.subject, t.opened_at, t.closed_at,
                  t.last_customer_message_at, t.last_sender_user_id,
                  c.id AS conversation_id, c.channel_type, c.channel_id, c.last_event_at, c.last_message_at,
                  -- user channel：直接用 channel_id 找 customer
                  -- group/room channel：用 last_sender_user_id 找最後發訊的人
                  COALESCE(cu_direct.id,   cu_sender.id)           AS customer_id,
                  COALESCE(cu_direct.display_name, cu_sender.display_name) AS display_name,
                  COALESCE(cu_direct.picture_url,  cu_sender.picture_url)  AS picture_url,
                  COALESCE(cu_direct.phone,        cu_sender.phone)        AS phone,
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
                -- user channel 直接 JOIN
                LEFT JOIN customers cu_direct ON cu_direct.line_user_id=c.channel_id
                                              AND c.channel_type='user'
                -- group/room channel 用 last_sender_user_id JOIN
                LEFT JOIN customers cu_sender ON cu_sender.line_user_id=t.last_sender_user_id
                                              AND c.channel_type IN ('group','room')
                LEFT JOIN assignments a ON a.ticket_id=t.id AND a.status='active'
                WHERE t.status IN ({placeholders})
                ORDER BY COALESCE(t.last_customer_message_at, c.last_message_at, t.opened_at) DESC
                LIMIT %s OFFSET %s
                """,
                (*statuses, limit, offset),
            )
            rows = cur.fetchall()

            if autofill_subject:
                for r in rows:
                    if not (r.get("subject") or "").strip():
                        first_text = (r.get("first_in_text") or "").strip()
                        if first_text:
                            new_subj = _normalize_subject(first_text)
                            cur.execute("UPDATE tickets SET subject=%s, updated_at=NOW() WHERE id=%s",
                                        (new_subj, r["ticket_id"]))
                            r["subject"] = new_subj

        conn.commit()
        return {"ok": True, "items": rows, "limit": limit, "offset": offset}
    finally:
        conn.close()


@router.get("/tickets/{ticket_id}/messages")
def get_ticket_messages(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=200, ge=1, le=500),
):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, conversation_id, ticket_id, direction, message_type, text,
                       content_path, content_mime, content_size, content_name, content_url,
                       sticker_id, package_id, sticker_resource_type, sticker_url,
                       sender_type, sender_name, sender_picture_url, staff_id, created_at
                FROM messages_raw WHERE ticket_id=%s ORDER BY id LIMIT %s
                """,
                (ticket_id, limit),
            )
            rows = cur.fetchall()
        return {"ok": True, "items": rows}
    finally:
        conn.close()


@router.post("/tickets/{ticket_id}/reply")
def reply_ticket(ticket_id: int, body: ReplyBody, staff: dict = Depends(get_current_staff)):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    agent_name = (body.agent_name or DEFAULT_AGENT_NAME).strip()
    staff_id   = int(staff.get("staff_id"))
    staff_name = (staff.get("name") or "客服").strip()

    conn = get_conn()
    try:
        ticket = _get_ticket(conn, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="ticket not found")

        channel_id = (ticket.get("channel_id") or "").strip() or (ticket.get("conversation_channel_id") or "").strip()
        if not channel_id:
            raise HTTPException(status_code=400, detail="ticket has no channel_id")

        _assign_if_needed(conn, ticket_id, agent_name)
        code, body_text, payload = line_push(channel_id, text)

        raw_obj = {"line_push_status": code, "line_push_body": body_text, "payload": payload,
                   "note": body.note, "agent_name": agent_name, "staff_id": staff_id, "staff_name": staff_name}

        _insert_outgoing_message_raw(conn, int(ticket["conversation_id"]), ticket_id, text, raw_obj, staff_id, staff_name)
        _fill_ticket_subject_if_missing(conn, ticket_id)
        _touch_after_reply(conn, ticket_id)

        conn.commit()
        return {"ok": True, "line_status": code}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.post("/tickets/{ticket_id}/close")
def close_ticket(ticket_id: int, body: CloseBody, staff: dict = Depends(get_current_staff)):
    conn = get_conn()
    try:
        ticket = _get_ticket(conn, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="ticket not found")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tickets SET status='closed', closed_at=NOW(), updated_at=NOW() "
                "WHERE id=%s AND status <> 'closed'",
                (ticket_id,),
            )
        _release_active_assignment(conn, ticket_id)
        conn.commit()
        return {"ok": True, "note": body.note}
    except HTTPException:
        conn.rollback(); raise
    except Exception as e:
        conn.rollback(); raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/staff/me")
def staff_me(staff: dict = Depends(get_current_staff)):
    return {"ok": True, "staff": staff}


@router.get("/stats/questions")
def stats_questions(
    staff: dict = Depends(get_current_staff),
    days: int = Query(default=7, ge=1, le=60),
    limit: int = Query(default=2000, ge=10, le=20000),
):
    require_admin_staff(staff)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT text FROM messages_raw
                WHERE direction='in' AND message_type='text'
                  AND created_at >= (NOW() - INTERVAL %s DAY)
                  AND text IS NOT NULL AND text <> ''
                ORDER BY id DESC LIMIT %s
                """,
                (days, limit),
            )
            rows = cur.fetchall()
        # 詞頻統計（你原本有 extract_question_phrases，請保留引入）
        phrases = []
        for r in rows:
            t = (r.get("text") or "").strip()
            if t:
                phrases.append(t)
        counter: dict[str, int] = {}
        for p in phrases:
            counter[p] = counter.get(p, 0) + 1
        items = [{"phrase": k, "count": v} for k, v in sorted(counter.items(), key=lambda x: x[1], reverse=True)]
        return {"ok": True, "days": days, "limit": limit, "items": items}
    finally:
        conn.close()


@router.post("/staff/tokens/create")
def staff_token_create(body: TokenCreateBody, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    if body.staff_id <= 0:
        raise HTTPException(status_code=400, detail="staff_id required")
    raw = generate_admin_token()
    th  = sha256_hex(raw)
    tp  = token_prefix(raw)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO staff_tokens (staff_id, token_hash, token_prefix, label) VALUES (%s, %s, %s, %s)",
                (int(body.staff_id), th, tp, body.label or None),
            )
            token_id = cur.lastrowid
        conn.commit()
        return {"ok": True, "token_id": token_id, "token": raw, "token_prefix": tp}
    finally:
        conn.close()


@router.post("/staff/tokens/revoke")
def staff_token_revoke(body: TokenRevokeBody, staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    if body.token_id <= 0:
        raise HTTPException(status_code=400, detail="token_id required")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE staff_tokens SET revoked_at=NOW() WHERE id=%s AND revoked_at IS NULL",
                (int(body.token_id),),
            )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@router.get("/staff/{staff_id}/tokens")
def staff_tokens_list(staff_id: int, staff: dict = Depends(get_current_staff)):
    me_staff_id = int(staff["staff_id"])
    if staff.get("role") != "admin" and staff_id != me_staff_id:
        raise HTTPException(status_code=403, detail="forbidden")
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, token_prefix, label, created_at, last_used_at, revoked_at "
                "FROM staff_tokens WHERE staff_id=%s ORDER BY id DESC",
                (staff_id,),
            )
            rows = cur.fetchall()
        return {"ok": True, "items": rows}
    finally:
        conn.close()


@router.get("/content/{line_message_id}")
def get_content(line_message_id: str, staff: dict = Depends(get_current_staff)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, content_path, content_mime, content_name FROM messages_raw "
                "WHERE line_message_id=%s LIMIT 1",
                (line_message_id,),
            )
            row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="content not found")

        if not row.get("content_path"):
            try:
                data, mime = _fetch_line_content(line_message_id)
                _ensure_dir(LINE_CONTENT_DIR)
                ext   = _MIME_EXT.get(mime, "")
                fname = f"{line_message_id}{ext}"
                fpath = os.path.join(LINE_CONTENT_DIR, fname)
                with open(fpath, "wb") as f:
                    f.write(data)
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE messages_raw SET content_path=%s, content_mime=%s, content_size=%s, "
                        "content_name=%s, content_url=%s WHERE id=%s",
                        (fpath, mime, len(data), fname, f"/admin/api/content/{line_message_id}", row["id"]),
                    )
                    conn.commit()
                row["content_path"] = fpath
                row["content_mime"]  = mime
                row["content_name"]  = fname
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"fetch content failed: {e}")

        return FileResponse(
            row["content_path"],
            media_type=row.get("content_mime") or "application/octet-stream",
            filename=row.get("content_name") or None,
        )
    finally:
        conn.close()


# ── ✅ emoji endpoint（只保留一個，整合兩版最完整的邏輯）──────

@router.get("/emoji/{product_id}/{emoji_id}")
def get_emoji(product_id: str, emoji_id: str, staff: dict = Depends(get_current_staff)):
    """
    LINE emoji 代理：/admin/api/emoji/{product_id}/{emoji_id}
    策略：先讀本機快取，沒有才去 LINE 抓並存檔。
    原本有兩個重複 endpoint，現合併為此一個。
    """
    safe_product = product_id.replace("/", "_").strip()
    safe_emoji   = emoji_id.replace("/", "_").strip()

    folder = os.path.join(LINE_EMOJI_DIR, safe_product)
    _ensure_dir(folder)

    # 1) 快取命中
    for ext, mime in [(".png", "image/png"), (".webp", "image/webp"), (".gif", "image/gif")]:
        fpath = os.path.join(folder, f"{safe_emoji}{ext}")
        if os.path.exists(fpath):
            return FileResponse(
                fpath, media_type=mime,
                filename=os.path.basename(fpath),
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

    # 2) 快取未命中：從 LINE 抓
    try:
        data, mime = _fetch_line_emoji(safe_product, safe_emoji)
        ext = ".webp" if mime == "image/webp" else (".gif" if mime == "image/gif" else ".png")
        fpath = os.path.join(folder, f"{safe_emoji}{ext}")
        with open(fpath, "wb") as f:
            f.write(data)
        return FileResponse(
            fpath, media_type=mime,
            filename=os.path.basename(fpath),
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fetch emoji failed: {e}")
