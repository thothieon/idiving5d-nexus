# app/quick_reply_handler.py  ── idiving5d-OctoFlow v260310
# ============================================================
# Quick Reply 核心邏輯
# - 從 DB 載入規則（帶簡單 in-memory cache，60 秒 TTL）
# - 組裝 LINE Quick Reply message
# ============================================================
import json
import time
from typing import Optional

from app.db import get_conn

# ── In-memory cache（避免每則訊息都查 DB）───────────────────
_CACHE: dict = {
    "rules": [],        # list of {keyword, reply_text, buttons}
    "loaded_at": 0.0,
}
_CACHE_TTL = 60.0       # 秒，60 秒後自動重新載入


# 從資料庫載入所有啟用中的 Quick Reply 規則，並存入 in-memory cache
async def _load_rules() -> list[dict]:
    """從 DB 載入所有 is_active=1 的規則，結果存進 cache"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT keyword, reply_text, buttons "
                "FROM quick_reply_rules WHERE is_active=1 ORDER BY id ASC"
            )
            rows = await cur.fetchall()

    rules = []
    for r in rows:
        buttons = r["buttons"]
        if isinstance(buttons, str):
            buttons = json.loads(buttons)
        rules.append({
            "keyword":    r["keyword"],
            "reply_text": r["reply_text"],
            "buttons":    buttons,   # [{"label": "5/1", "url": "https://..."}]
        })
    return rules


# 取得 Quick Reply 規則清單，優先使用 cache（60 秒 TTL），過期才重新查 DB
async def get_rules() -> list[dict]:
    """取得規則（優先用 cache，過期才重新查 DB）"""
    now = time.monotonic()
    if now - _CACHE["loaded_at"] > _CACHE_TTL:
        _CACHE["rules"]     = await _load_rules()
        _CACHE["loaded_at"] = now
    return _CACHE["rules"]


# 強制讓 cache 失效，後台更新規則後呼叫以確保下次重新從 DB 載入
async def invalidate_cache():
    """後台更新規則後呼叫，強制下次重新載入"""
    _CACHE["loaded_at"] = 0.0


# 以完全符合方式比對訊息文字，回傳第一個符合的規則，無符合則回傳 None
async def match_rule(text: str) -> Optional[dict]:
    """
    完全符合比對。
    回傳第一個符合的 rule dict，沒有符合回傳 None。
    """
    text = (text or "").strip()
    if not text:
        return None
    rules = await get_rules()
    for rule in rules:
        if rule["keyword"] == text:
            return rule
    return None


# 依據規則組裝 LINE Quick Reply 訊息 payload，按鈕最多 13 個，label 最多 20 字
def build_quick_reply_message(rule: dict) -> dict:
    """
    組裝 LINE Quick Reply message payload。

    LINE Quick Reply 規格：
    - items 最多 13 個
    - label 最多 20 字元
    - URIAction：點下去開啟瀏覽器
    """
    buttons = rule["buttons"][:13]  # 安全截斷

    quick_reply_items = [
        {
            "type": "action",
            "action": {
                "type":  "uri",
                "label": btn["label"][:20],   # LINE 限制 20 字
                "uri":   btn["url"],
            }
        }
        for btn in buttons
    ]

    return {
        "type": "text",
        "text": rule["reply_text"],
        "quickReply": {
            "items": quick_reply_items
        }
    }
