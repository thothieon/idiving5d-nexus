# linebotapp_idiving_callback.py  (FastAPI version, no Flask Blueprint)
import os
import json
import hmac
import base64
import hashlib
from datetime import datetime, timezone
from typing import Optional, Tuple

import requests
import pymysql
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import PlainTextResponse

# ----------------------------
# ENV
# ----------------------------
TZ = os.environ.get("TZ", "Asia/Taipei")

DB_HOST = os.environ.get("DB_HOST", "192.168.12.159")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "rootpwd")
DB_NAME = os.environ.get("DB_NAME", "iDiving_LineTest")

LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# ----------------------------
# Router
# ----------------------------
router = APIRouter()

# ----------------------------
# DB helpers
# ----------------------------
def get_conn():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )

# ----------------------------
# LINE helpers
# ----------------------------
def _line_headers():
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
    url = f"https://api.line.me/v2/bot/group/{group_id}/summary"
    r = requests.get(url, headers=_line_headers(), timeout=10)
    if r.status_code != 200:
        print("[WARN] get_group_summary failed:", r.status_code, r.text)
        return None
    return r.json()

def get_room_members_count(room_id: str) -> Optional[int]:
    if not room_id:
        return None
    url = f"https://api.line.me/v2/bot/room/{room_id}/members/count"
    r = requests.get(url, headers=_line_headers(), timeout=10)
    if r.status_code != 200:
        print("[WARN] get_room_members_count failed:", r.status_code, r.text)
        return None
    data = r.json() or {}
    return data.get("count")

def get_group_members_count(group_id: str) -> Optional[int]:
    if not group_id:
        return None
    url = f"https://api.line.me/v2/bot/group/{group_id}/members/count"
    r = requests.get(url, headers=_line_headers(), timeout=10)
    if r.status_code != 200:
        print("[WARN] get_group_members_count failed:", r.status_code, r.text)
        return None
    data = r.json() or {}
    return data.get("count")

def _now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _extract_source(event: dict) -> tuple[str | None, str | None]:
    """
    回傳 (channel_type, channel_id)
    channel_type: user / group / room
    channel_id: userId / groupId / roomId
    """
    src = event.get("source") or {}
    st = src.get("type")
    if st == "user":
        return "user", src.get("userId")
    if st == "group":
        return "group", src.get("groupId")
    if st == "room":
        return "room", src.get("roomId")
    return None, None


def refresh_group_or_room_cache(event: dict):
    """
    先做「不會炸」版本：只要是 group/room 就嘗試打 LINE API 拿 summary/count。
    你之後想把資料寫入 DB（例如 conversations.group_name / member_count）再加。
    """
    ctype, cid = _extract_source(event)
    if ctype == "group" and cid:
        summary = get_group_summary(cid)  # 你上面已經有 def get_group_summary
        # 你可以在這裡把 summary["groupName"] 寫進 DB
        # print("[DEBUG] group summary:", summary)
        return
    if ctype == "room" and cid:
        cnt = get_room_members_count(cid)  # 你上面已經有 def get_room_members_count
        # 你可以在這裡把 cnt 寫進 DB
        # print("[DEBUG] room members count:", cnt)
        return
    return

def insert_message_raw_if_any(conn, event: dict, event_id: str):
    """
    最小版：只處理 message 事件，把 text/image/sticker 的基本資料塞 messages_raw
    """
    if event.get("type") != "message":
        return

    msg = event.get("message") or {}
    mtype = msg.get("type")
    line_message_id = msg.get("id")

    # who said?
    ctype, cid = _extract_source(event)
    sender_type = "customer"
    sender_name = None
    sender_picture_url = None

    text = msg.get("text") if mtype == "text" else None

    content_url = None
    sticker_id = None
    package_id = None
    sticker_resource_type = None

    if mtype == "sticker":
        sticker_id = msg.get("stickerId")
        package_id = msg.get("packageId")
        sticker_resource_type = msg.get("stickerResourceType")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages_raw
              (event_id, line_message_id, direction, message_type, text, raw_json,
               sender_type, sender_name, sender_picture_url,
               content_url, sticker_id, package_id, sticker_resource_type,
               created_at)
            VALUES
              (%s, %s, 'in', %s, %s, %s,
               %s, %s, %s,
               %s, %s, %s, %s,
               NOW())
            """,
            (
                event_id,
                line_message_id,
                mtype,
                text,
                json.dumps(event, ensure_ascii=False),
                sender_type,
                sender_name,
                sender_picture_url,
                content_url,
                sticker_id,
                package_id,
                sticker_resource_type,
            ),
        )


def get_or_create_conversation(conn, event: dict) -> int:
    ctype, cid = _extract_source(event)
    if not ctype or not cid:
        raise RuntimeError("cannot determine channel_type/channel_id from event.source")

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM conversations
            WHERE channel_type=%s AND channel_id=%s
            LIMIT 1
            """,
            (ctype, cid),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])

        cur.execute(
            """
            INSERT INTO conversations (channel_type, channel_id, created_at, updated_at, last_event_at, last_message_at)
            VALUES (%s, %s, NOW(), NOW(), NOW(), NOW())
            """,
            (ctype, cid),
        )
        return int(cur.lastrowid)


def touch_conversation(conn, conversation_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE conversations SET last_event_at=NOW(), updated_at=NOW() WHERE id=%s",
            (conversation_id,),
        )


def ensure_ticket_for_conversation(conn, conversation_id: int, event: dict) -> int:
    """
    最小版：同一個 conversation 找 open/pending ticket，沒有就開新的
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM tickets
            WHERE conversation_id=%s AND status IN ('open','pending')
            ORDER BY id DESC
            LIMIT 1
            """,
            (conversation_id,),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])

        # 開新 ticket
        cur.execute(
            """
            INSERT INTO tickets (conversation_id, status, opened_at, created_at, updated_at)
            VALUES (%s, 'open', NOW(), NOW(), NOW())
            """,
            (conversation_id,),
        )
        return int(cur.lastrowid)


def final_fixup_for_message(event: dict, event_id: str):
    """
    先做 no-op / 保留接口，避免 NameError。
    你原本如果有「補 last_message_id / channel_id」的修補 SQL，就放這裡。
    """
    return

# 放在 routes_callback.py 的 business logic 區塊（# Routes 之前）
_line_events_cols_cache = None

def _detect_line_events_columns(conn) -> set[str]:
    global _line_events_cols_cache
    if _line_events_cols_cache is not None:
        return _line_events_cols_cache

    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM line_events")
        cols = [r["Field"] for r in cur.fetchall()]
    _line_events_cols_cache = set(cols)
    return _line_events_cols_cache


def insert_line_event(conn, event: dict) -> str:
    """
    寫入 line_events：欄位用 SHOW COLUMNS 動態適配，避免 Unknown column。
    """
    # 1) 先保證 event_id 一定有值（就算 DB insert 失敗，log 也能追）
    raw = json.dumps(event, ensure_ascii=False, sort_keys=True)
    ev_id = (event.get("webhookEventId") or event.get("eventId") or "").strip()
    if not ev_id:
        ev_id = "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    etype = (event.get("type") or "").strip()

    # 2) 來源（group/user/room + id）
    src = event.get("source") or {}
    src_type = src.get("type")
    src_id = src.get("userId") or src.get("groupId") or src.get("roomId")

    cols = _detect_line_events_columns(conn)

    # 3) 挑「你 DB 可能存在」的欄位名（多候選）
    # event_id 欄位（通常一定會有）
    event_id_col = "event_id" if "event_id" in cols else ("id" if "id" in cols else None)

    # event type 欄位
    event_type_col = None
    for c in ["event_type", "type", "eventName"]:
        if c in cols:
            event_type_col = c
            break

    # channel_type 欄位（你的 DB 現在沒有，所以會自動略過）
    channel_type_col = None
    for c in ["channel_type", "source_type"]:
        if c in cols:
            channel_type_col = c
            break

    # channel_id 欄位
    channel_id_col = None
    for c in ["channel_id", "source_id", "uid", "user_id", "line_user_id"]:
        if c in cols:
            channel_id_col = c
            break

    # raw json 欄位
    raw_col = None
    for c in ["raw_json", "raw", "payload", "body_json", "event_json"]:
        if c in cols:
            raw_col = c
            break

    # created_at 欄位
    created_col = None
    for c in ["created_at", "createdAt", "created"]:
        if c in cols:
            created_col = c
            break

    if not event_id_col:
        # 沒有 event_id 欄位就沒法寫（這代表表設計不符預期）
        raise RuntimeError("line_events has no usable event_id column (event_id/id)")

    insert_cols = []
    placeholders = []
    params = []

    # event_id
    insert_cols.append(f"`{event_id_col}`")
    placeholders.append("%s")
    params.append(ev_id)

    # event_type (可有可無)
    if event_type_col:
        insert_cols.append(f"`{event_type_col}`")
        placeholders.append("%s")
        params.append(etype)

    # channel_type (可無)
    if channel_type_col:
        insert_cols.append(f"`{channel_type_col}`")
        placeholders.append("%s")
        params.append(src_type)

    # channel_id (可無)
    if channel_id_col:
        insert_cols.append(f"`{channel_id_col}`")
        placeholders.append("%s")
        params.append(src_id)

    # raw_json (可無)
    if raw_col:
        insert_cols.append(f"`{raw_col}`")
        placeholders.append("%s")
        params.append(raw)

    # created_at (如果有就 NOW())
    if created_col:
        insert_cols.append(f"`{created_col}`")
        placeholders.append("NOW()")

    sql_cols = ", ".join(insert_cols)
    sql_vals = ", ".join(placeholders)

    # 4) 去重策略：
    # - 如果 event_id_col 是 UNIQUE KEY：用 ON DUPLICATE KEY UPDATE 會比較安全
    # - update 哪些欄位？raw / type 存在才更新
    updates = []
    update_params = []

    if raw_col:
        updates.append(f"`{raw_col}`=VALUES(`{raw_col}`)")
    if event_type_col:
        updates.append(f"`{event_type_col}`=VALUES(`{event_type_col}`)")
    if channel_type_col:
        updates.append(f"`{channel_type_col}`=VALUES(`{channel_type_col}`)")
    if channel_id_col:
        updates.append(f"`{channel_id_col}`=VALUES(`{channel_id_col}`)")

    ondup = ""
    if updates:
        ondup = " ON DUPLICATE KEY UPDATE " + ", ".join(updates)

    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO line_events ({sql_cols}) VALUES ({sql_vals}){ondup}",
            tuple(params),
        )

    return ev_id



# ----------------------------
# Your existing business logic (DB insert / conversation / tickets)
# ----------------------------
# ⚠️ 下面這一段，你原本檔案裡的函式（insert_line_event / insert_message_raw_if_any /
# get_or_create_conversation / touch_conversation / ensure_ticket_for_conversation /
# final_fixup_for_message / refresh_group_or_room_cache ...）請「原封不動」保留。
#
# 我在這裡不重打你全部內容，避免你貼上時不小心漏掉你自己的邏輯。
#
# ✅ 你要做的事：把原檔中「Routes 區塊以上」的那些函式全部保留下來（不改或少改）
#    然後只把最底下的 Routes 區塊換成下面 FastAPI 的版本。

# ----------------------------
# Routes
# ----------------------------
@router.get("/health")
async def health():
    return {"ok": True}

@router.post("/idiving_callback_test")
async def idiving_callback_test(req: Request):
    data = {}
    try:
        data = await req.json()
    except Exception:
        data = {}
    print("\nHello from FastAPI idiving_callback_test in Docker!~~~789~")
    return {"ok": True, "echo": data}

@router.post("/callback", response_class=PlainTextResponse)
async def callback(
    req: Request,
    x_line_signature: str | None = Header(default=None, alias="X-Line-Signature"),
):
    raw_body = await req.body()
    signature = x_line_signature or ""

    if not verify_line_signature(raw_body, signature):
        raise HTTPException(status_code=400, detail="Bad signature")

    # 解析 JSON（用 raw_body 解析比較穩，避免 request.json() 讀兩次 body）
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
            # 0) group/room 即時更新（失敗也不能中斷主流程）
            try:
                refresh_group_or_room_cache(event)
            except Exception as e:
                print("[WARN] refresh_group_or_room_cache error:", e)

            conn = get_conn()
            try:
                # 1) line_events
                event_id = insert_line_event(conn, event)

                # 2) messages_raw（如果是 message）
                insert_message_raw_if_any(conn, event, event_id)

                # 3) conversation
                conversation_id = get_or_create_conversation(conn, event)
                touch_conversation(conn, conversation_id)

                # 4) ticket
                ticket_id = ensure_ticket_for_conversation(conn, conversation_id, event)

                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

            # 6) 最後保險補洞：避免再出現 C>0
            if event.get("type") == "message" and event_id:
                final_fixup_for_message(event, event_id)

        except Exception as e:
            print("[ERROR] handle event failed:", e, "event_id=", event_id)
            continue

    return "OK"
