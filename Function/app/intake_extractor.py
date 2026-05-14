# app/intake_extractor.py  ── idiving5d-OctoFlow
# ================================================================
# 被動 AI 萃取：從客人對話文字中自動識別結構化資訊 + 意圖分類
# 使用 Google Gemini API（支援 Gemma 系列模型）
# 以背景任務執行，不阻塞 webhook 回應
# ================================================================
import os
import json
import asyncio

from google import genai

from app.db import get_conn
from app.rag_retriever import retrieve_relevant_chunks, format_rag_context

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemma-3-27b-it")

_FIELD_DESC = """\
- customer_name    : 客人姓名（中文或英文皆可）
- phone            : 聯絡電話（含區碼皆保留）
- course_type      : 課程類型，如：水肺初級、進階水肺、OW、AOW、自由潛水、水中攝影等
- preferred_date   : 希望上課日期，保留原始說法，如「下週六」「5月初」「2026-05-10」
- group_size       : 報名人數（整數）
- experience_level : 潛水經驗，從以下選一：無/初學/有執照/進階，若無法判斷則 null
- notes            : 其他重要備註（過敏、特殊需求、指定教練等）
- suggested_reply  : 根據對話，建議客服接下來回覆的文字（繁體中文、口語自然、30~80字）。
                     若意圖是 course_inquiry 則說明課程並詢問需求；
                     若是 booking 則確認報名細節；
                     若是 payment 則提供繳費說明；
                     若是 complaint 則先致歉再處理；
                     若是 general 則親切回應。此欄位不可為 null，必填。
- intent           : 本次對話主要意圖，從以下選一（只能選一個）：
    course_inquiry  → 詢問課程內容、費用、時間、師資等
    booking         → 明確表達要報名、預約、確認名額
    payment         → 詢問付款方式、匯款、繳費相關
    complaint       → 抱怨、反映問題、不滿
    general         → 閒聊、感謝、其他無明確意圖
- intent_confidence: 意圖判斷的信心分數，0~100 的整數\
"""

_SYSTEM = (
    "你是潛水中心客服系統的資訊萃取模組。"
    "從客人的對話訊息中找出以下欄位的值，只回傳合法 JSON，不要任何解釋文字。"
    "如果某個欄位在對話中完全沒有提到，該欄位值為 null。"
    "intent 與 intent_confidence 必填，不可為 null。"
)

_KEY_FIELDS = ("customer_name", "phone", "course_type", "preferred_date", "group_size")

_VALID_INTENTS = {"course_inquiry", "booking", "payment", "complaint", "general"}

_INTENT_LABEL = {
    "course_inquiry": "詢問課程",
    "booking":        "要報名",
    "payment":        "繳費相關",
    "complaint":      "抱怨反映",
    "general":        "一般閒聊",
}


def _calc_completeness(data: dict) -> int:
    filled = sum(1 for f in _KEY_FIELDS if data.get(f) not in (None, "", 0))
    return int(filled / len(_KEY_FIELDS) * 100)


async def _fetch_recent_texts(conn, conversation_id: int, limit: int = 20) -> list[dict]:
    """取得該 conversation 最近 N 則文字訊息（含方向與發送者名稱）"""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT direction, sender_name, text
            FROM   messages_raw
            WHERE  conversation_id = %s
              AND  message_type = 'text'
              AND  text IS NOT NULL
              AND  direction IN ('in', 'out')
            ORDER  BY created_at DESC
            LIMIT  %s
            """,
            (conversation_id, limit),
        )
        rows = await cur.fetchall()
    return list(reversed(rows))


def _format_messages(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        who = "客人" if r["direction"] == "in" else "客服"
        name = (r.get("sender_name") or "").strip() or who
        lines.append(f"[{name}]: {r['text']}")
    return "\n".join(lines)


def _strip_fence(raw: str) -> str:
    """去除 Gemini 有時包的 ```json ... ``` markdown fence"""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _validate_intent(data: dict) -> dict:
    """確保 intent 在合法範圍內，不合法則 fallback 為 general"""
    intent = (data.get("intent") or "").strip()
    if intent not in _VALID_INTENTS:
        data["intent"] = "general"
    confidence = data.get("intent_confidence")
    try:
        data["intent_confidence"] = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        data["intent_confidence"] = 50
    return data


async def _call_google(messages_text: str, rag_context: str = "") -> dict | None:
    """呼叫 Google Gemini / Gemma API 萃取欄位，回傳 dict 或 None（失敗時）
    503 / 429 自動 retry，最多 3 次，間隔 5 → 15 → 30 秒
    """
    if not GOOGLE_API_KEY:
        print("[intake] GOOGLE_API_KEY 未設定，跳過萃取")
        return None

    rag_section = f"\n\n{rag_context}\n" if rag_context else ""
    prompt = (
        f"{_SYSTEM}\n\n"
        f"欄位定義：\n{_FIELD_DESC}\n"
        f"{rag_section}"
        f"\n對話內容：\n{messages_text}"
    )

    client  = genai.Client(api_key=GOOGLE_API_KEY)
    delays  = [5, 15, 30]

    for attempt, delay in enumerate(delays, start=1):
        try:
            resp = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            raw = _strip_fence(resp.text)
            return json.loads(raw)

        except json.JSONDecodeError as e:
            print(f"[intake] Gemini 回傳非 JSON: {e}")
            return None   # JSON 錯誤重試沒意義

        except Exception as e:
            err_str = str(e)
            is_retryable = ("503" in err_str or "429" in err_str or
                            "UNAVAILABLE" in err_str or "RESOURCE_EXHAUSTED" in err_str)

            if is_retryable and attempt < len(delays):
                print(f"[intake] Gemini 暫時不可用，{delay}s 後重試（第 {attempt} 次）: {e}")
                await asyncio.sleep(delay)
            else:
                print(f"[intake] Google API 呼叫失敗: {e}")
                return None

    return None


async def _upsert_intake(
    conn,
    conversation_id: int,
    ticket_id: int,
    data: dict,
    rag_sources: list[dict] | None = None,
):
    """將萃取結果寫入 conversation_intakes（已有欄位不覆蓋，逐步累積；意圖與建議回覆永遠更新）"""
    data         = _validate_intent(data)
    completeness = _calc_completeness(data)
    rag_json     = json.dumps(
        [{"id": c["id"], "title": c["title"], "score": c["score"]} for c in (rag_sources or [])]
    )

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO conversation_intakes
              (conversation_id, ticket_id,
               customer_name, phone, course_type, preferred_date,
               group_size, experience_level, notes, suggested_reply,
               intent, intent_confidence,
               completeness, rag_sources, created_at, updated_at)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
              ticket_id           = VALUES(ticket_id),
              customer_name       = COALESCE(VALUES(customer_name),    customer_name),
              phone               = COALESCE(VALUES(phone),            phone),
              course_type         = COALESCE(VALUES(course_type),      course_type),
              preferred_date      = COALESCE(VALUES(preferred_date),   preferred_date),
              group_size          = COALESCE(VALUES(group_size),       group_size),
              experience_level    = COALESCE(VALUES(experience_level), experience_level),
              notes               = COALESCE(VALUES(notes),            notes),
              suggested_reply     = VALUES(suggested_reply),
              intent              = VALUES(intent),
              intent_confidence   = VALUES(intent_confidence),
              completeness        = GREATEST(completeness, VALUES(completeness)),
              rag_sources         = VALUES(rag_sources),
              updated_at          = NOW()
            """,
            (
                conversation_id, ticket_id,
                data.get("customer_name"), data.get("phone"),
                data.get("course_type"),   data.get("preferred_date"),
                data.get("group_size"),    data.get("experience_level"),
                data.get("notes"),         data.get("suggested_reply"),
                data.get("intent"),        data.get("intent_confidence"),
                completeness,             rag_json,
            ),
        )
    await conn.commit()


async def run_intake_extraction(conversation_id: int, ticket_id: int):
    """
    背景執行入口：取對話 → RAG 召回 → 呼叫 Google AI → 寫入 DB
    由 routes_callback._handle_event 以 asyncio.create_task 呼叫
    """
    try:
        async with get_conn() as conn:
            rows = await _fetch_recent_texts(conn, conversation_id)
            if not rows:
                return

            messages_text = _format_messages(rows)

            rag_chunks  = await retrieve_relevant_chunks(conn, messages_text)
            rag_context = format_rag_context(rag_chunks)

            data = await _call_google(messages_text, rag_context=rag_context)
            if not data:
                return

            data = _validate_intent(data)
            await _upsert_intake(conn, conversation_id, ticket_id, data, rag_sources=rag_chunks)

            intent_label = _INTENT_LABEL.get(data.get("intent", ""), data.get("intent", ""))
            print(
                f"[intake] conversation={conversation_id} "
                f"intent={intent_label}({data.get('intent_confidence')}%) "
                f"completeness={_calc_completeness(data)}% "
                f"fields={[k for k, v in data.items() if v not in (None, '', 0) and k not in ('intent','intent_confidence','completeness')]}"
            )
    except Exception as e:
        print(f"[intake] 背景萃取失敗 conversation={conversation_id}: {e}")
