# app/routes_callback.py  ── idiving5d-OctoFlow v260310
import os
import time
import json
import hmac
import base64
import hashlib
import mimetypes
import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import PlainTextResponse

from app.db import get_conn
from app.session_manager import on_customer_message
from app.quick_reply_handler import match_rule, build_quick_reply_message

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

# 組裝 LINE API 請求所需的 Authorization 標頭
def _line_headers() -> dict:
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is empty")
    return {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


# 驗證 LINE Webhook 請求簽章，防止偽造請求
def verify_line_signature(raw_body: bytes, signature_b64: str) -> bool:
    if not LINE_CHANNEL_SECRET:
        raise RuntimeError("LINE_CHANNEL_SECRET is empty")
    mac = hmac.new(LINE_CHANNEL_SECRET.encode("utf-8"), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature_b64 or "")


# 從 LINE event 中萃取來源類型（user/group/room）與對應 ID
def _extract_source(event: dict) -> tuple[str | None, str | None]:
    src = event.get("source") or {}
    st  = src.get("type")
    if st == "user":  return "user",  src.get("userId")
    if st == "group": return "group", src.get("groupId")
    if st == "room":  return "room",  src.get("roomId")
    return None, None


# 從 LINE event 中取得發送者的 userId
def _extract_user_id(event: dict) -> Optional[str]:
    return (event.get("source") or {}).get("userId")


# ── async LINE API calls ─────────────────────────────────────

# 以非同步方式對 LINE API 發送 GET 請求，回傳狀態碼與 JSON 回應
async def _async_get(url: str, params: dict | None = None) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers=_line_headers(), params=params)
        return r.status_code, (r.json() if r.status_code == 200 else {})


# 向 LINE API 查詢群組摘要資訊（群組名稱、圖片等）
async def get_group_summary(group_id: str) -> Optional[dict]:
    if not group_id:
        return None
    status, data = await _async_get(f"https://api.line.me/v2/bot/group/{group_id}/summary")
    return data if status == 200 else None


# 向 LINE API 查詢聊天室成員人數
async def get_room_members_count(room_id: str) -> Optional[int]:
    if not room_id:
        return None
    status, data = await _async_get(f"https://api.line.me/v2/bot/room/{room_id}/members/count")
    return data.get("count") if status == 200 else None


# 從 LINE API 取得個人用戶的個人資料（顯示名稱、頭貼等）
async def _fetch_line_profile(user_id: str) -> dict | None:
    if not LINE_CHANNEL_ACCESS_TOKEN or user_id.startswith(("C", "R")):
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"https://api.line.me/v2/bot/profile/{user_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
            )
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


# 從 LINE API 下載訊息的媒體內容（圖片、影片、音訊、檔案），回傳二進位資料與 MIME 類型
async def fetch_line_message_content(line_message_id: str) -> tuple[bytes, str]:
    url = f"https://api-data.line.me/v2/bot/message/{line_message_id}/content"
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"})
    if r.status_code != 200:
        raise RuntimeError(f"fetch content failed: {r.status_code}")
    mime = (r.headers.get("content-type") or "").split(";")[0].strip() or "application/octet-stream"
    return r.content, mime


# ── group/room 快取刷新 ──────────────────────────────────────

# 依事件來源刷新群組或聊天室的快取資訊至資料庫（背景執行不阻塞主流程）
async def refresh_group_or_room_cache(event: dict):
    ctype, cid = _extract_source(event)
    if ctype == "group" and cid:
        summary = await get_group_summary(cid)
        if summary:
            try:
                async with get_conn() as conn:
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
                            (cid, summary.get("groupName"), summary.get("pictureUrl")),
                        )
                    await conn.commit()
            except Exception as e:
                print("[WARN] refresh_group_or_room_cache write failed:", e)
        return

    if ctype == "room" and cid:
        cnt = await get_room_members_count(cid)
        if cnt is not None:
            try:
                async with get_conn() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            INSERT INTO line_channels (channel_type, channel_id, member_count, updated_at)
                            VALUES ('room', %s, %s, NOW())
                            ON DUPLICATE KEY UPDATE
                                member_count = VALUES(member_count),
                                updated_at   = NOW()
                            """,
                            (cid, cnt),
                        )
                    await conn.commit()
            except Exception as e:
                print("[WARN] refresh_group_or_room_cache (room) write failed:", e)


# ── customers 自動建立 ───────────────────────────────────────

# 確保事件的發送用戶已存在於 customers 表，不存在則自動建立並補齊 LINE 個人資料
async def ensure_customer_from_event(conn, event: dict):
    user_id = _extract_user_id(event)
    if not user_id:
        return

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO customers (line_user_id, created_at, updated_at)
            VALUES (%s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE updated_at = updated_at
            """,
            (user_id,),
        )

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, display_name, picture_url FROM customers WHERE line_user_id=%s LIMIT 1",
            (user_id,),
        )
        row = await cur.fetchone()

    if not row:
        return

    if row.get("display_name") and row.get("picture_url"):
        return

    if user_id.startswith(("C", "R")):
        return

    profile = await _fetch_line_profile(user_id)
    if not profile:
        return

    dname = (profile.get("displayName") or "").strip() or None
    pic   = (profile.get("pictureUrl")  or "").strip() or None

    if dname or pic:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE customers
                SET display_name = COALESCE(%s, display_name),
                    picture_url  = COALESCE(%s, picture_url),
                    updated_at   = NOW()
                WHERE line_user_id = %s
                """,
                (dname, pic, user_id),
            )


# ── line_events 寫入 ─────────────────────────────────────────

# 將 LINE 原始事件寫入 line_events 資料表，回傳事件 ID
async def insert_line_event(conn, event: dict) -> str:
    raw   = json.dumps(event, ensure_ascii=False, sort_keys=True)
    ev_id = (event.get("webhookEventId") or event.get("eventId") or "").strip()
    if not ev_id:
        ev_id = "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    etype    = (event.get("type") or "").strip()
    src      = event.get("source") or {}
    src_type = src.get("type")
    user_id  = src.get("userId")

    ts_ms    = event.get("timestamp")
    event_ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if ts_ms else None

    async with conn.cursor() as cur:
        await cur.execute(
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


# 補填 line_events 記錄的 conversation_id 與 ticket_id 關聯
async def _update_line_event_refs(conn, event_id: str, conversation_id: int, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE line_events SET conversation_id=%s, ticket_id=%s WHERE event_id=%s",
            (conversation_id, ticket_id, event_id),
        )


# ── conversation / ticket 管理 ───────────────────────────────

# 查詢或建立對應此 LINE event 的 conversation 記錄，回傳 conversation_id
async def get_or_create_conversation(conn, event: dict) -> int:
    ctype, cid = _extract_source(event)
    if not ctype or not cid:
        raise RuntimeError("cannot determine channel_type/channel_id from event.source")

    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id FROM conversations WHERE channel_type=%s AND channel_id=%s LIMIT 1",
            (ctype, cid),
        )
        row = await cur.fetchone()
        if row:
            return int(row["id"])

        customer_id = None
        if ctype == "user":
            user_id = _extract_user_id(event)
            if user_id:
                await cur.execute("SELECT id FROM customers WHERE line_user_id=%s LIMIT 1", (user_id,))
                c = await cur.fetchone()
                if c:
                    customer_id = int(c["id"])

        await cur.execute(
            """
            INSERT INTO conversations
              (channel_type, channel_id, customer_id, created_at, updated_at, last_event_at, last_message_at)
            VALUES (%s, %s, %s, NOW(), NOW(), NOW(), NOW())
            ON DUPLICATE KEY UPDATE
              last_event_at = NOW(),
              updated_at    = NOW()
            """,
            (ctype, cid, customer_id),
        )
        # ON DUPLICATE KEY: lastrowid 在 update 時為 0，需重查
        if cur.lastrowid:
            return int(cur.lastrowid)
        await cur.execute(
            "SELECT id FROM conversations WHERE channel_id=%s LIMIT 1", (cid,)
        )
        row = await cur.fetchone()
        return int(row["id"])


# 更新 conversation 的最後事件時間戳記
async def touch_conversation(conn, conversation_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE conversations SET last_event_at=NOW(), updated_at=NOW() WHERE id=%s",
            (conversation_id,),
        )


# 確保指定 conversation 有 open/pending 的 ticket，無則自動建立，回傳 ticket_id
async def ensure_ticket_for_conversation(conn, conversation_id: int, channel_id: str) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id FROM tickets WHERE conversation_id=%s AND status IN ('open','pending') "
            "ORDER BY id DESC LIMIT 1",
            (conversation_id,),
        )
        row = await cur.fetchone()
        if row:
            return int(row["id"])

        await cur.execute(
            """
            INSERT INTO tickets
              (conversation_id, channel_id, status, opened_at, created_at, updated_at)
            VALUES (%s, %s, 'open', NOW(), NOW(), NOW())
            """,
            (conversation_id, channel_id),
        )
        return int(cur.lastrowid)


# 更新 ticket 的最後收訊時間戳記
async def touch_ticket_on_message(conn, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE tickets SET last_customer_message_at=NOW(), updated_at=NOW() WHERE id=%s",
            (ticket_id,),
        )


# ── 訊息存檔 ─────────────────────────────────────────────────

# 確保指定目錄存在，不存在則遞迴建立
def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


# 將 LINE 媒體內容依 MIME 類型儲存至磁碟，回傳路徑、大小與檔名
def save_content_to_disk(line_message_id: str, data: bytes, mime: str) -> tuple[str, int, str]:
    _ensure_dir(LINE_CONTENT_DIR)
    ext = _MIME_EXT.get(mime) or mimetypes.guess_extension(mime) or ""
    content_name = f"{line_message_id}{ext}"
    content_path = os.path.join(LINE_CONTENT_DIR, content_name)
    with open(content_path, "wb") as f:
        f.write(data)
    return content_path, len(data), content_name


# 若 event 為 message 類型，將訊息內容（含媒體檔案）寫入 messages_raw 資料表
async def insert_message_raw_if_any(conn, event: dict, event_id: str, conversation_id: int, ticket_id: int):
    if event.get("type") != "message":
        return

    msg             = event.get("message") or {}
    mtype           = (msg.get("type") or "").strip()
    line_message_id = (msg.get("id") or "").strip()
    if not line_message_id:
        return

    text = msg.get("text") if mtype == "text" else None

    sender_name = sender_picture_url = None
    user_id = _extract_user_id(event)
    if user_id:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT display_name, picture_url FROM customers WHERE line_user_id=%s LIMIT 1",
                (user_id,),
            )
            cu = await cur.fetchone()
            if cu:
                sender_name        = cu.get("display_name")
                sender_picture_url = cu.get("picture_url")

    content_path = content_mime = content_name = content_url = None
    content_size = None
    sticker_id = package_id = sticker_resource_type = sticker_url = None

    if mtype == "sticker":
        sticker_id            = msg.get("stickerId")
        package_id            = msg.get("packageId")
        sticker_resource_type = msg.get("stickerResourceType")

    if mtype in ("image", "video", "audio", "file"):
        try:
            data, mime   = await fetch_line_message_content(line_message_id)
            content_path, content_size, content_name = save_content_to_disk(line_message_id, data, mime)
            content_mime = mime
            content_url  = f"/admin/api/content/{line_message_id}"
        except Exception as e:
            print("[WARN] fetch/save content failed:", e)

        if mtype == "file":
            fn = (msg.get("fileName") or "").strip()
            if fn: content_name = fn
            fs = msg.get("fileSize")
            if fs and not content_size:
                try: content_size = int(fs)
                except Exception: pass

    async with conn.cursor() as cur:
        await cur.execute(
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

# 將系統事件（如 follow/unfollow）寫入 messages_raw，讓客服在對話中看到提示
async def _insert_system_message(conn, conversation_id: int, ticket_id: int, text: str):
    event_id = f"sys_{ticket_id}_{int(time.time() * 1000)}"
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT IGNORE INTO messages_raw
              (event_id, conversation_id, ticket_id, line_message_id,
               direction, message_type, text, raw_json,
               sender_type, sender_name, created_at)
            VALUES (%s, %s, %s, NULL, 'system', 'text', %s, '{}', 'system', '系統', NOW())
            """,
            (event_id, conversation_id, ticket_id, text),
        )


#async 推送 Quick Reply 的 helper function
async def _send_quick_reply(channel_id: str, rule: dict):
    """
    送出 Quick Reply 訊息給指定的 channel。
    使用 LINE push message API。
    """
    msg = build_quick_reply_message(rule)
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": channel_id,
        "messages": [msg],
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.line.me/v2/bot/message/push",
                headers=headers,
                json=payload,
            )
        if r.status_code != 200:
            print(f"[WARN] quick_reply push failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[WARN] quick_reply push error: {e}")



# ── Routes ───────────────────────────────────────────────────

# 健康檢查端點：確認 callback 服務正常運行
@router.get("/health")
async def health():
    return {"ok": True, "version": "idiving5d-OctoFlow v260310"}


# 測試用 callback endpoint：接收任意 JSON 並原封不動回傳（echo）
@router.post("/idiving_callback_test")
async def idiving_callback_test(req: Request):
    try:
        data = await req.json()
    except Exception:
        data = {}
    return {"ok": True, "echo": data}


# LINE Webhook 主要接收端點：驗證簽章後並行處理所有事件
@router.post("/callback", response_class=PlainTextResponse)
async def callback(
    req: Request,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
):
    raw_body  = await req.body()
    signature = x_line_signature or ""

    if not verify_line_signature(raw_body, signature):
        import hmac as _hmac, hashlib as _hs, base64 as _b64
        expected = _b64.b64encode(_hmac.new(LINE_CHANNEL_SECRET.encode(), raw_body, _hs.sha256).digest()).decode()
        print(f"[DEBUG] sig_recv={signature!r} sig_expect={expected!r} body_len={len(raw_body)}")
        raise HTTPException(status_code=400, detail="Bad signature")

    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    events = body.get("events") or []
    if not isinstance(events, list):
        raise HTTPException(status_code=400, detail="Invalid body")

    # 所有 event 並行處理
    await asyncio.gather(*[_handle_event(event) for event in events], return_exceptions=True)

    return "OK"


# 處理單一 LINE 事件：依序完成用戶建立、事件記錄、對話/Ticket 管理、訊息存檔與狀態機推進
async def _handle_event(event: dict):
    """單一 event 處理邏輯，從 callback 抽出方便 gather"""
    event_id = None
    try:
        # 0) group/room 資訊刷新（不阻塞主流程）
        asyncio.create_task(refresh_group_or_room_cache(event))

        async with get_conn() as conn:
            # 1) 確保 customers 有此用戶
            await ensure_customer_from_event(conn, event)

            # 2) line_events
            event_id = await insert_line_event(conn, event)

            # 3) conversation
            _, channel_id = _extract_source(event)
            conversation_id = await get_or_create_conversation(conn, event)
            await touch_conversation(conn, conversation_id)

            # 4) ticket
            ticket_id = await ensure_ticket_for_conversation(conn, conversation_id, channel_id or "")

            # 5) line_events 補 refs
            await _update_line_event_refs(conn, event_id, conversation_id, ticket_id)

            # 6) messages_raw
            await insert_message_raw_if_any(conn, event, event_id, conversation_id, ticket_id)

            # 7) ticket 收訊時間戳 + 狀態機
            if event.get("type") == "message":
                await touch_ticket_on_message(conn, ticket_id)
                await on_customer_message(conn, ticket_id)

                # ── Quick Reply 關鍵字偵測 ──────────────────
                msg_obj  = event.get("message") or {}
                msg_text = (msg_obj.get("text") or "").strip()
                if msg_text:
                    rule = await match_rule(msg_text)
                    if rule and channel_id:
                        # commit 先寫入，再推送 Quick Reply
                        await conn.commit()
                        await _send_quick_reply(channel_id, rule)
                        return          # 已 commit，直接返回

            elif event.get("type") == "follow":
                await _insert_system_message(conn, conversation_id, ticket_id, "📲 客人重新加入 LINE@")
                await touch_ticket_on_message(conn, ticket_id)

            elif event.get("type") == "unfollow":
                await _insert_system_message(conn, conversation_id, ticket_id, "⚠️ 客人已移除 LINE@，推播將無法送達")

            await conn.commit()

    except Exception as e:
        print("[ERROR] handle event failed:", e, "event_id=", event_id)
