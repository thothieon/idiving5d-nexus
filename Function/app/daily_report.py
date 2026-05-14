# app/daily_report.py  ── idiving5d-OctoFlow
# ================================================================
# 每日 AI 摘要報告
#
# 每天 22:00（Asia/Taipei）自動執行：
#   1. 查詢今日統計數字（訊息、工單、意圖、超時等）
#   2. 組合結構化分類報告（_build_report）
#   3. 請 Gemini 附加一行 AI 觀察（可選）
#   4. 用 LINE push 推播給管理者（LINE_NOTIFY_TO_ID）
#
# 也提供手動觸發：POST /admin/api/stats/line/daily_report
# ================================================================
import os
import asyncio
import datetime
import zoneinfo

import httpx
from google import genai

from app.db import get_conn

LINE_TOKEN     = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_NOTIFY_TO = os.environ.get("LINE_NOTIFY_TO_ID", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GEMINI_MODEL   = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
TZ             = zoneinfo.ZoneInfo("Asia/Taipei")

INTENT_LABELS = {
    "course_inquiry": "詢問課程",
    "booking":        "要報名",
    "payment":        "繳費相關",
    "complaint":      "抱怨反映",
    "general":        "一般閒聊",
}


# ── 資料查詢 ────────────────────────────────────────────────────

async def _fetch_today_stats() -> dict:
    """查詢今日所需統計數字"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:

            # 今日客人訊息 / 客服回覆
            await cur.execute("""
                SELECT
                  SUM(direction='in')                          AS msgs_in,
                  SUM(direction='out' AND sender_type='staff') AS msgs_out
                FROM messages_raw
                WHERE DATE(created_at) = CURDATE()
            """)
            msg = await cur.fetchone()

            # 今日尖峰時段（客人傳入訊息最多的小時）
            await cur.execute("""
                SELECT HOUR(created_at) AS hr, COUNT(*) AS cnt
                FROM messages_raw
                WHERE DATE(created_at) = CURDATE() AND direction='in'
                GROUP BY hr
                ORDER BY cnt DESC
                LIMIT 1
            """)
            peak = await cur.fetchone()

            # 今日新工單 / 今日結案 / 目前狀態
            await cur.execute("""
                SELECT
                  SUM(DATE(created_at) = CURDATE())  AS today_new,
                  SUM(DATE(closed_at)  = CURDATE())  AS today_closed,
                  SUM(current_status = 'open')        AS open_cnt,
                  SUM(current_status = 'pending')     AS pending_cnt
                FROM tickets
            """)
            tk = await cur.fetchone()

            # 今日各客服回覆則數
            await cur.execute("""
                SELECT sender_name AS name, COUNT(*) AS cnt
                FROM messages_raw
                WHERE DATE(created_at) = CURDATE()
                  AND direction='out' AND sender_type='staff'
                GROUP BY sender_name
                ORDER BY cnt DESC
                LIMIT 8
            """)
            staff_rows = await cur.fetchall()

            # 今日新客數（對話首次開工單）
            await cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM tickets t
                WHERE DATE(t.created_at) = CURDATE()
                  AND NOT EXISTS (
                    SELECT 1 FROM tickets t2
                    WHERE t2.conversation_id = t.conversation_id
                      AND t2.id < t.id
                  )
            """)
            new_cust = await cur.fetchone()

            # 超時工單列表（open 且最後客人訊息距今 > 60 分，附等待分鐘數）
            await cur.execute("""
                SELECT t.id,
                       COALESCE(
                           cu_direct.customer_name,
                           cu_sender.customer_name,
                           cu_direct.display_name,
                           cu_sender.display_name,
                           '未知'
                       ) AS name,
                       TIMESTAMPDIFF(MINUTE,
                           (SELECT MAX(m.created_at) FROM messages_raw m
                            WHERE m.ticket_id = t.id AND m.direction='in'),
                           NOW()
                       ) AS wait_minutes
                FROM tickets t
                JOIN conversations cv ON cv.id = t.conversation_id
                LEFT JOIN customers cu_direct
                    ON cu_direct.line_user_id = cv.channel_id AND cv.channel_type = 'user'
                LEFT JOIN customers cu_sender
                    ON cu_sender.line_user_id = cv.channel_id AND cv.channel_type IN ('group','room')
                WHERE t.current_status = 'open'
                HAVING wait_minutes > 60
                ORDER BY wait_minutes DESC
                LIMIT 5
            """)
            overdue_rows = await cur.fetchall()

            # 今日意圖分佈（前 5）
            await cur.execute("""
                SELECT intent, COUNT(*) AS cnt
                FROM conversation_intakes
                WHERE DATE(updated_at) = CURDATE() AND intent IS NOT NULL
                GROUP BY intent
                ORDER BY cnt DESC
                LIMIT 5
            """)
            intents = await cur.fetchall()

            # 近 7 天最熱課程（前 5）
            await cur.execute("""
                SELECT course_type, COUNT(*) AS cnt
                FROM conversation_intakes
                WHERE course_type IS NOT NULL AND course_type != ''
                  AND updated_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                GROUP BY course_type
                ORDER BY cnt DESC
                LIMIT 5
            """)
            courses = await cur.fetchall()

            # 最久未結案（前 3 張，附等待天數）
            await cur.execute("""
                SELECT t.id, t.current_status,
                       COALESCE(
                           cu_direct.customer_name,
                           cu_sender.customer_name,
                           cu_direct.display_name,
                           cu_sender.display_name,
                           '未知'
                       ) AS name,
                       DATEDIFF(NOW(), t.opened_at) AS wait_days
                FROM tickets t
                JOIN conversations cv ON cv.id = t.conversation_id
                LEFT JOIN customers cu_direct
                    ON cu_direct.line_user_id = cv.channel_id AND cv.channel_type = 'user'
                LEFT JOIN customers cu_sender
                    ON cu_sender.line_user_id = cv.channel_id AND cv.channel_type IN ('group','room')
                WHERE t.current_status NOT IN ('closed')
                ORDER BY t.opened_at ASC
                LIMIT 3
            """)
            oldest = await cur.fetchall()

    return {
        "msgs_in":       int(msg["msgs_in"]     or 0),
        "msgs_out":      int(msg["msgs_out"]    or 0),
        "peak_hour":     int(peak["hr"])         if peak else None,
        "peak_hour_cnt": int(peak["cnt"])        if peak else 0,
        "today_new":     int(tk["today_new"]    or 0),
        "today_closed":  int(tk["today_closed"] or 0),
        "open_cnt":      int(tk["open_cnt"]     or 0),
        "pending_cnt":   int(tk["pending_cnt"]  or 0),
        "new_customers": int(new_cust["cnt"]    or 0),
        "staff_replies": [{"name": r["name"], "cnt": int(r["cnt"])} for r in staff_rows],
        "overdue_tickets": [
            {"id": r["id"], "name": r["name"], "wait_minutes": int(r["wait_minutes"] or 0)}
            for r in overdue_rows
        ],
        "intents": [
            {"label": INTENT_LABELS.get(r["intent"], r["intent"]), "cnt": int(r["cnt"])}
            for r in intents
        ],
        "courses":  [{"course_type": r["course_type"], "cnt": int(r["cnt"])} for r in courses],
        "oldest_tickets": [
            {"id": r["id"], "name": r["name"], "status": r["current_status"],
             "wait_days": int(r["wait_days"] or 0)}
            for r in oldest
        ],
    }


# ── 結構化報告組合 ───────────────────────────────────────────────

def _build_report(stats: dict) -> str:
    today = datetime.date.today().strftime("%Y/%m/%d")
    SEP   = "─" * 22
    lines = [f"📊 iDiving 每日客服摘要 {today}", SEP]

    # 📨 訊息流量
    reply_rate = round(stats["msgs_out"] / stats["msgs_in"] * 100) if stats["msgs_in"] else 0
    lines.append("📨 訊息流量")
    flow = f"  收到 {stats['msgs_in']} 則｜回覆 {stats['msgs_out']} 則｜回覆率 {reply_rate}%"
    if stats["peak_hour"] is not None:
        flow += f"\n  尖峰：{stats['peak_hour']:02d}:00（{stats['peak_hour_cnt']} 則）"
    lines.append(flow)

    # 🎫 工單概況
    lines.append("🎫 工單概況")
    lines.append(f"  今日新開 {stats['today_new']} 張｜今日結案 {stats['today_closed']} 張")
    lines.append(f"  open {stats['open_cnt']} 張｜pending {stats['pending_cnt']} 張")

    # 👥 客服出勤
    if stats["staff_replies"]:
        lines.append("👥 客服出勤")
        lines.append("  " + "｜".join(f"{s['name']} {s['cnt']}則" for s in stats["staff_replies"]))
        if stats["new_customers"]:
            lines.append(f"  新客戶 {stats['new_customers']} 位初次來訊")

    # ⚠️ 超時未回
    if stats["overdue_tickets"]:
        lines.append(f"⚠️ 超時未回（>60分）{len(stats['overdue_tickets'])} 張")
        for t in stats["overdue_tickets"]:
            h = t["wait_minutes"] / 60
            lines.append(f"  · #{t['id']} {t['name']}｜等待 {h:.1f} 小時")

    # 🔍 今日詢問主題
    if stats["intents"]:
        lines.append("🔍 今日詢問主題")
        lines.append("  " + "｜".join(f"{i['label']} ×{i['cnt']}" for i in stats["intents"]))

    # 🤿 近 7 日熱門課程
    if stats["courses"]:
        lines.append("🤿 近 7 日熱門課程")
        lines.append("  " + "｜".join(f"{c['course_type']} ×{c['cnt']}" for c in stats["courses"]))

    # 📌 最久未結案
    if stats["oldest_tickets"]:
        lines.append("📌 最久未結案")
        for t in stats["oldest_tickets"]:
            lines.append(f"  · #{t['id']} {t['name']}（{t['status']}）等待 {t['wait_days']} 天")

    return "\n".join(lines)


# ── AI 一行觀察 ──────────────────────────────────────────────────

async def _ai_insight(stats: dict) -> str:
    """請 Gemini 根據數據生成一行觀察，失敗則回傳空字串"""
    if not GOOGLE_API_KEY:
        return ""

    parts = []
    if stats["overdue_tickets"]:
        parts.append(f"超時工單 {len(stats['overdue_tickets'])} 張")
    if stats["intents"]:
        top = stats["intents"][0]
        parts.append(f"主要詢問：{top['label']}×{top['cnt']}")
    if stats["courses"]:
        top = stats["courses"][0]
        parts.append(f"熱門課程：{top['course_type']}×{top['cnt']}")
    reply_rate = round(stats["msgs_out"] / stats["msgs_in"] * 100) if stats["msgs_in"] else 0
    parts.append(f"回覆率 {reply_rate}%")

    prompt = (
        "你是 iDiving 潛水中心客服系統 AI。"
        f"今日數據：{'、'.join(parts)}。"
        "請用繁體中文寫一句話（40字以內）的觀察或行動建議，語氣簡潔直接，不要任何前綴符號。"
    )
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        resp   = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=prompt
        )
        text = (resp.text or "").strip().splitlines()[0]
        return f"🤖 {text}" if text else ""
    except Exception as e:
        print(f"[daily_report] Gemini AI 觀察失敗: {e}")
        return ""


# ── LINE 推播 ────────────────────────────────────────────────────

async def _push_line(text: str):
    if not LINE_TOKEN or not LINE_NOTIFY_TO:
        print("[daily_report] LINE_CHANNEL_ACCESS_TOKEN 或 LINE_NOTIFY_TO_ID 未設定，跳過推播")
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.line.me/v2/bot/message/push",
                headers={
                    "Authorization": f"Bearer {LINE_TOKEN}",
                    "Content-Type":  "application/json",
                },
                json={
                    "to":       LINE_NOTIFY_TO,
                    "messages": [{"type": "text", "text": text}],
                },
            )
        if resp.status_code != 200:
            print(f"[daily_report] LINE push 失敗: {resp.status_code} {resp.text[:200]}")
        else:
            print("[daily_report] LINE push 成功")
    except Exception as e:
        print(f"[daily_report] LINE push 例外: {e}")


# ── 主入口 ──────────────────────────────────────────────────────

async def run_daily_report():
    """查詢數據 → 組合報告 → AI 觀察 → LINE 推播"""
    print("[daily_report] 開始生成每日摘要…")
    try:
        stats   = await _fetch_today_stats()
        report  = _build_report(stats)
        insight = await _ai_insight(stats)
        msg     = report + (f"\n{insight}" if insight else "")
        await _push_line(msg)
        print(f"[daily_report] 完成，報告長度={len(msg)}")
    except Exception as e:
        print(f"[daily_report] 執行失敗: {e}")


# ── 排程器（由 main.py lifespan 啟動）──────────────────────────

async def daily_report_scheduler():
    """每天 22:00 Asia/Taipei 自動執行 run_daily_report"""
    while True:
        now    = datetime.datetime.now(TZ)
        target = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target:
            target += datetime.timedelta(days=1)
        wait   = (target - now).total_seconds()
        print(f"[daily_report] 下次執行：{target.strftime('%Y-%m-%d %H:%M')}（{int(wait/60)} 分後）")
        await asyncio.sleep(wait)
        await run_daily_report()
