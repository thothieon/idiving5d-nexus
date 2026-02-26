# app/routes_callback.py
# ============================================================
# 修改清單：
#   1. 移除本地 get_conn()，改從 app.db import
#   2. 移除 _detect_line_events_columns() 動態偵測
#   3. insert_line_event() 改用固定欄位（對應新 Schema）
#   4. 新增 ensure_customer_from_event()：收到訊息時自動建立 customers 記錄
# ============================================================
import os
import json
import hmac
import base64
import hashlib
import mimetypes
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import PlainTextResponse

from app.db import get_conn
from app.session_manager import on_customer_message

# ── ENV ──────────────────────────────────────────────────────
LINE_CHANNEL_SECRET       = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CONTENT_DIR          = os.environ.get("LINE_CONTENT_DIR", "/app/data/line_content").strip() or "/app/data/line_content"

_MIME_EXT = {
    "image/jpeg":      ".jpg",
    "image/png":       ".png",
    "image/gif":       ".gif",
    "image/webp":      ".webp",
    "video/mp4":       ".mp4",
    "audio/mpeg":      ".mp3",
    "audio/mp4":       ".m4a",
    "audio/aac":       ".aac",
    "application/pdf": ".pdf",
}

router = APIRouter()


# ── LINE helpers ─────────────────────────────────────────────

def _line_headers() -> dict:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is empty")
    return {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def verify_line_signature(raw_body: bytes, signature_b64: str) -> bool:
    if not LINE_CHANNEL_SECRET:
        raise RuntimeError("LINE_CHANNEL_SECRET is empty")
    mac = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature_b64 or "")


def get_group_summary(group_id: str) -> Optional[dict]:
    if not group_id:
        return None
    r = requests.get(f"https://api.line.me/v2/bot/group/{group_id}/summary",
                     headers=_line_headers(), timeout=10)
    if r.status_code != 200:
        print("[WARN] get_group_summary failed:", r.status_code, r.text)
        return None
    return r.json()


def get_room_members_count(room_id: str) -> Optional[int]:
    if not room_id:
        return None
    r = requests.get(f"https://api.line.me/v2/bot/room/{room_id}/members/count",
                     headers=_line_headers(), timeout=10)
    if r.status_code != 200:
        print("[WARN] get_room_members_count failed:", r.status_code, r.text)
        return None
    return (r.json() or {}).get("count")


def get_group_members_count(group_id: str) -> Optional[int]:
    if not group_id:
        return None
    r = requests.get(f"https://api.line.me/v2/bot/group/{group_id}/members/count",
                     headers=_line_headers(), timeout=10)
    if r.status_code != 200:
        print("[WARN] get_group_members_count failed:", r.status_code, r.text)
        return None
    return (r.json() or {}).get("count")


# ── Source helpers ───────────────────────────────────────────

def _extract_source(event: dict) -> tuple[str | None, str | None]:
    """回傳 (channel_type, channel_id)"""
    src = event.get("source") or {}
    st  = src.get("type")
    if st == "user":  return "user",  src.get("userId")
    if st == "group": return "group", src.get("groupId")
    if st == "room":  return "room",  src.get("roomId")
    return None, None


def _extract_user_id(event: dict) -> Optional[str]:
    """取出送出這個事件的 LINE userId（group/room 也會有）"""
    return (event.get("source") or {}).get("userId")


# ── group/room 快取刷新 ──────────────────────────────────────

def refresh_group_or_room_cache(event: dict):
    """
    收到 group/room 事件時，順帶更新 line_channels 表的群組資訊。
    失敗不影響主流程。
    """
    ctype, cid = _extract_source(event)
    if ctype == "group" and cid:
        summary = get_group_summary(cid)
        if summary:
            try:
                conn = get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO line_channels (channel_type, channel_id, display_name, picture_url, updated_at)
                            VALUES ('group', %s, %s, %s, NOW())
                            ON DUPLICATE KEY UPDATE
                                display_name = VALUES(display_name),
                                picture_url  = VALUES(picture_url),
                                updated_at   = NOW()
                            """,
                            (cid, summary.get("groupName"), summary.get("pictureUrl")),
                        )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                print("[WARN] refresh_group_or_room_cache write failed:", e)
        return

    if ctype == "room" and cid:
        cnt = get_room_members_count(cid)
        if cnt is not None:
            try:
                conn = get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO line_channels (channel_type, channel_id, member_count, updated_at)
                            VALUES ('room', %s, %s, NOW())
                            ON DUPLICATE KEY UPDATE
                                member_count = VALUES(member_count),
                                updated_at   = NOW()
                            """,
                            (cid, cnt),
                        )
                    conn.commit()
                finally:
                    conn.close()
            except Exception as e:
                print("[WARN] refresh_group_or_room_cache (room) write failed:", e)


# ── customers 自動建立 ───────────────────────────────────────

def _fetch_line_profile(user_id: str) -> dict | None:
    """向 LINE API 取得用戶 profile（displayName, pictureUrl）"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return None
    try:
        r = requests.get(
            f"https://api.line.me/v2/bot/profile/{user_id}",
            headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            timeout=5,
        )
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def ensure_customer_from_event(conn, event: dict):
    """
    每次收到事件，如果能取得 userId 就確保 customers 表裡有這筆記錄。
    display_name 留空沒關係，之後由 /audiences/profiles 補齊。
    
    每次收到事件，確保 customers 表有此用戶。
    若 display_name 或 picture_url 為空，即時向 LINE 補齊。
    """
    user_id = _extract_user_id(event)
    if not user_id:
        return

    # Step 1: INSERT OR IGNORE
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customers (line_user_id, created_at, updated_at)
            VALUES (%s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE updated_at = updated_at
            """,
            (user_id,),
        )

    # Step 2: 檢查是否需要補 profile
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, display_name, picture_url FROM customers WHERE line_user_id=%s LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return

    needs_profile = not row.get("display_name") or not row.get("picture_url")
    if not needs_profile:
        return

    # Step 3: 向 LINE 拿 profile（group/room 開頭的不是 userId，跳過）
    if user_id.startswith(("C", "R")):
        return

    profile = _fetch_line_profile(user_id)
    if not profile:
        return

    dname = (profile.get("displayName") or "").strip() or None
    pic   = (profile.get("pictureUrl")  or "").strip() or None

    if dname or pic:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE customers
                SET display_name = COALESCE(%s, display_name),
                    picture_url  = COALESCE(%s, picture_url),
                    updated_at   = NOW()
                WHERE line_user_id = %s
                """,
                (dname, pic, user_id),
            )


# ── line_events 寫入（固定欄位，問題五修正）─────────────────

def insert_line_event(conn, event: dict) -> str:
    """
    寫入 line_events。
    改動：移除動態 SHOW COLUMNS，直接對應新 Schema 固定欄位。
    """
    raw   = json.dumps(event, ensure_ascii=False, sort_keys=True)
    ev_id = (event.get("webhookEventId") or event.get("eventId") or "").strip()
    if not ev_id:
        ev_id = "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    etype    = (event.get("type") or "").strip()
    src      = event.get("source") or {}
    src_type = src.get("type")                                          # user / group / room
    user_id  = src.get("userId")                                        # 送出事件的人

    # event_ts：LINE 給的 timestamp 是毫秒 epoch
    ts_ms    = event.get("timestamp")
    event_ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ts_ms else None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO line_events
              (event_id, event_type, source_type, user_id, event_ts, raw_json, created_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
              raw_json   = VALUES(raw_json),
              event_ts   = VALUES(event_ts),
              event_type = VALUES(event_type)
            """,
            (ev_id, etype, src_type, user_id, event_ts, raw),
        )

    return ev_id


def _update_line_event_refs(conn, event_id: str, conversation_id: int, ticket_id: int):
    """insert_line_event 寫入後，補上 conversation_id / ticket_id"""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE line_events SET conversation_id=%s, ticket_id=%s WHERE event_id=%s",
            (conversation_id, ticket_id, event_id),
        )


# ── conversation / ticket 管理 ───────────────────────────────

def get_or_create_conversation(conn, event: dict) -> int:
    ctype, cid = _extract_source(event)
    if not ctype or not cid:
        raise RuntimeError("cannot determine channel_type/channel_id from event.source")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM conversations WHERE channel_type=%s AND channel_id=%s LIMIT 1",
            (ctype, cid),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])

        # user channel：綁定 customer_id
        customer_id = None
        if ctype == "user":
            user_id = _extract_user_id(event)
            if user_id:
                cur.execute("SELECT id FROM customers WHERE line_user_id=%s LIMIT 1", (user_id,))
                c = cur.fetchone()
                if c:
                    customer_id = int(c["id"])

        cur.execute(
            """
            INSERT INTO conversations
              (channel_type, channel_id, customer_id, created_at, updated_at, last_event_at, last_message_at)
            VALUES (%s, %s, %s, NOW(), NOW(), NOW(), NOW())
            """,
            (ctype, cid, customer_id),
        )
        return int(cur.lastrowid)


def touch_conversation(conn, conversation_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE conversations SET last_event_at=NOW(), updated_at=NOW() WHERE id=%s",
            (conversation_id,),
        )


def ensure_ticket_for_conversation(conn, conversation_id: int, channel_id: str) -> int:
    """
    找 open/pending ticket；沒有就開新的。
    channel_id 快取存進 tickets.channel_id，方便 push 時直接取用。
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM tickets WHERE conversation_id=%s AND status IN ('open','pending') "
            "ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])

        cur.execute(
            """
            INSERT INTO tickets
              (conversation_id, channel_id, status, opened_at, created_at, updated_at)
            VALUES (%s, %s, 'open', NOW(), NOW(), NOW())
            """,
            (conversation_id, channel_id),
        )
        return int(cur.lastrowid)


def touch_ticket_on_message(conn, ticket_id: int):
    """收到客戶訊息時更新 last_customer_message_at"""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tickets SET last_customer_message_at=NOW(), updated_at=NOW() WHERE id=%s",
            (ticket_id,),
        )


# ── 訊息存檔 ─────────────────────────────────────────────────

def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def fetch_line_message_content(line_message_id: str) -> tuple[bytes, str]:
    url = f"https://api-data.line.me/v2/bot/message/{line_message_id}/content"
    r = requests.get(url, headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"fetch content failed: {r.status_code} {r.text}")
    mime = (r.headers.get("Content-Type") or "").split(";")[0].strip() or "application/octet-stream"
    return r.content, mime


def save_content_to_disk(line_message_id: str, data: bytes, mime: str) -> tuple[str, int, str]:
    """回傳 (content_path, content_size, content_name)"""
    _ensure_dir(LINE_CONTENT_DIR)
    ext = _MIME_EXT.get(mime) or mimetypes.guess_extension(mime) or ""
    content_name = f"{line_message_id}{ext}"
    content_path = os.path.join(LINE_CONTENT_DIR, content_name)
    with open(content_path, "wb") as f:
        f.write(data)
    return content_path, len(data), content_name


def insert_message_raw_if_any(conn, event: dict, event_id: str, conversation_id: int, ticket_id: int):
    if event.get("type") != "message":
        return

    msg             = event.get("message") or {}
    mtype           = (msg.get("type") or "").strip()
    line_message_id = (msg.get("id") or "").strip()
    if not line_message_id:
        return

    text = msg.get("text") if mtype == "text" else None

    # 從 customers 查出發送者 display_name / picture_url
    sender_name = None
    sender_picture_url = None
    user_id = _extract_user_id(event)
    if user_id:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT display_name, picture_url FROM customers WHERE line_user_id=%s LIMIT 1",
                (user_id,),
            )
            cu = cur.fetchone()
            if cu:
                sender_name        = cu.get("display_name")
                sender_picture_url = cu.get("picture_url")

    # content
    content_path = content_mime = content_name = content_url = None
    content_size = None

    # sticker
    sticker_id = package_id = sticker_resource_type = sticker_url = None

    if mtype == "sticker":
        sticker_id            = msg.get("stickerId")
        package_id            = msg.get("packageId")
        sticker_resource_type = msg.get("stickerResourceType")

    if mtype in ("image", "video", "audio", "file"):
        try:
            data, mime   = fetch_line_message_content(line_message_id)
            content_path, content_size, content_name = save_content_to_disk(line_message_id, data, mime)
            content_mime = mime
            content_url  = f"/admin/api/content/{line_message_id}"
        except Exception as e:
            print("[WARN] fetch/save content failed:", e, "line_message_id=", line_message_id)

        if mtype == "file":
            fn = (msg.get("fileName") or "").strip()
            if fn: content_name = fn
            fs = msg.get("fileSize")
            if fs and not content_size:
                try: content_size = int(fs)
                except Exception: pass

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages_raw
              (event_id, conversation_id, ticket_id, line_message_id,
               direction, message_type, text, raw_json,
               content_path, content_mime, content_size, content_name, content_url,
               sticker_id, package_id, sticker_resource_type, sticker_url,
               sender_type, sender_name, sender_picture_url,
               created_at)
            VALUES
              (%s, %s, %s, %s,
               'in', %s, %s, %s,
               %s, %s, %s, %s, %s,
               %s, %s, %s, %s,
               'customer', %s, %s,
               NOW())
            """,
            (
                event_id, conversation_id, ticket_id, line_message_id,
                mtype, text, json.dumps(event, ensure_ascii=False),
                content_path, content_mime, content_size, content_name, content_url,
                sticker_id, package_id, sticker_resource_type, sticker_url,
                sender_name, sender_picture_url,
            ),
        )


# ── Routes ───────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/idiving_callback_test")
async def idiving_callback_test(req: Request):
    try:
        data = await req.json()
    except Exception:
        data = {}
    return {"ok": True, "echo": data}


@router.post("/callback", response_class=PlainTextResponse)
async def callback(
    req: Request,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
):
    raw_body  = await req.body()
    signature = x_line_signature or ""

    if not verify_line_signature(raw_body, signature):
        raise HTTPException(status_code=400, detail="Bad signature")

    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events = body.get("events") or []
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="Invalid body")

    for event in events:
        event_id = None
        try:
            # 0) group/room 資訊刷新（失敗不中斷）
            try:
                refresh_group_or_room_cache(event)
            except Exception as e:
                print("[WARN] refresh_group_or_room_cache error:", e)

            conn = get_conn()
            try:
                # 1) 確保 customers 有此用戶
                ensure_customer_from_event(conn, event)

                # 2) line_events
                event_id = insert_line_event(conn, event)

                # 3) conversation
                _, channel_id = _extract_source(event)
                conversation_id = get_or_create_conversation(conn, event)
                touch_conversation(conn, conversation_id)

                # 4) ticket
                ticket_id = ensure_ticket_for_conversation(conn, conversation_id, channel_id or "")

                # 5) line_events 補 conversation_id / ticket_id
                _update_line_event_refs(conn, event_id, conversation_id, ticket_id)

                # 6) messages_raw
                insert_message_raw_if_any(conn, event, event_id, conversation_id, ticket_id)

                # 7) ticket 收訊時間戳
                if event.get("type") == "message":
                    touch_ticket_on_message(conn, ticket_id)
                    on_customer_message(conn, ticket_id)

                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        except Exception as e:
            print("[ERROR] handle event failed:", e, "event_id=", event_id)
            continue

    return "OK"
