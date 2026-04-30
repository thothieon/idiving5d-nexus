# app/daily_report.py  ── idiving5d-OctoFlow
# ================================================================
# 每日 AI 摘要報告
#
# 每天 22:00（Asia/Taipei）自動執行：
#   1. 查詢今日統計數字（訊息、工單、意圖、超時）
#   2. 請 Gemini 生成自然語言摘要
#   3. 用 LINE push 推播給管理者（LINE_NOTIFY_TO_ID）
#
# 也提供手動觸發：POST /admin/api/stats/line/daily_report
# ================================================================
import os
import json
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

            # 今日新工單 / 目前 open 工單
            await cur.execute("""
                SELECT
                  SUM(DATE(created_at) = CURDATE()) AS today_new,
                  SUM(current_status = 'open')      AS open_cnt,
                  SUM(current_status = 'pending')   AS pending_cnt
                FROM tickets
            """)
            tk = await cur.fetchone()

            # 超時工單（open 且最後客人訊息距今 > 60 分鐘）
            await cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM tickets t
                WHERE t.current_status = 'open'
                  AND EXISTS (
                    SELECT 1 FROM messages_raw m
                    WHERE m.ticket_id = t.id AND m.direction = 'in'
                    HAVING MAX(m.created_at) < DATE_SUB(NOW(), INTERVAL 60 MINUTE)
                  )
            """)
            overdue = (await cur.fetchone())["cnt"]

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

            # 近 7 天未結案（開最久的 3 張）
            await cur.execute("""
                SELECT t.id, t.current_status,
                       COALESCE(
                           cu_direct.customer_name,
                           cu_sender.customer_name,
                           cu_direct.display_name,
                           cu_sender.display_name,
                           '未知'
                       ) AS name,
                       t.opened_at
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

    intent_labels = {
        "course_inquiry": "詢問課程",
        "booking":        "要報名",
        "payment":        "繳費相關",
        "complaint":      "抱怨反映",
        "general":        "一般閒聊",
    }

    return {
        "msgs_in":   int(msg["msgs_in"]   or 0),
        "msgs_out":  int(msg["msgs_out"]  or 0),
        "today_new": int(tk["today_new"]  or 0),
        "open_cnt":  int(tk["open_cnt"]   or 0),
        "pending_cnt": int(tk["pending_cnt"] or 0),
        "overdue_cnt": int(overdue         or 0),
        "intents":   [{"label": intent_labels.get(r["intent"], r["intent"]), "cnt": r["cnt"]}
                      for r in intents],
        "courses":   [{"course_type": r["course_type"], "cnt": r["cnt"]} for r in courses],
        "oldest_tickets": [
            {"id": r["id"], "name": r["name"], "status": r["current_status"],
             "opened_at": str(r["opened_at"] or "")}
            for r in oldest
        ],
    }


# ── AI 摘要生成 ──────────────────────────────────────────────────

async def _generate_summary(stats: dict) -> str:
    """請 Gemini 根據數據生成自然語言摘要，失敗則回傳純文字版本"""
    if not GOOGLE_API_KEY:
        return _fallback_text(stats)

    intent_str  = "、".join(f"{i['label']}×{i['cnt']}" for i in stats["intents"]) or "（無）"
    course_str  = "、".join(f"{c['course_type']}×{c['cnt']}" for c in stats["courses"]) or "（無）"
    oldest_str  = "\n".join(
        f"  - #{t['id']} {t['name']}（{t['status']}）開單：{t['opened_at'][:10]}"
        for t in stats["oldest_tickets"]
    ) or "  - 無"

    prompt = (
        "你是 iDiving 潛水中心客服系統的 AI 助手。"
        "根據以下今日統計數字，用繁體中文撰寫一份簡短的每日摘要（150字以內），"
        "語氣親切、重點明確，最後若有超時工單或大量投訴則提醒客服注意。\n\n"
        f"【今日數據 - {datetime.date.today().strftime('%Y/%m/%d')}】\n"
        f"客人傳入訊息：{stats['msgs_in']} 則\n"
        f"客服回覆：{stats['msgs_out']} 則\n"
        f"今日新工單：{stats['today_new']} 張\n"
        f"目前 open（待回覆）：{stats['open_cnt']} 張\n"
        f"目前 pending（等客人）：{stats['pending_cnt']} 張\n"
        f"超時未回（>60分鐘）：{stats['overdue_cnt']} 張\n"
        f"今日意圖分佈：{intent_str}\n"
        f"近7日熱門課程：{course_str}\n"
        f"最久未結案工單：\n{oldest_str}\n\n"
        "請只輸出摘要文字，不要標題、不要 JSON。"
    )

    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        resp   = await client.aio.models.generate_content(
            model=GEMINI_MODEL, contents=prompt
        )
        text = (resp.text or "").strip()
        if text:
            return text
    except Exception as e:
        print(f"[daily_report] Gemini 生成摘要失敗，改用純文字版本: {e}")

    return _fallback_text(stats)


def _fallback_text(stats: dict) -> str:
    """Gemini 失敗時的純文字備用摘要"""
    today = datetime.date.today().strftime("%Y/%m/%d")
    lines = [
        f"📊 iDiving 每日客服摘要 {today}",
        f"",
        f"📨 今日訊息：客人 {stats['msgs_in']} 則 / 客服 {stats['msgs_out']} 則",
        f"🎫 今日新工單：{stats['today_new']} 張",
        f"📋 待處理：open {stats['open_cnt']}張 / pending {stats['pending_cnt']}張",
    ]
    if stats["overdue_cnt"]:
        lines.append(f"⚠️ 超時未回（>60分）：{stats['overdue_cnt']} 張，請盡快處理！")
    if stats["intents"]:
        intent_str = "、".join(f"{i['label']} {i['cnt']}次" for i in stats["intents"])
        lines.append(f"🤖 今日意圖：{intent_str}")
    if stats["courses"]:
        course_str = "、".join(f"{c['course_type']} {c['cnt']}次" for c in stats["courses"])
        lines.append(f"🤿 熱門詢問：{course_str}")
    return "\n".join(lines)


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
    """查詢數據 → 生成摘要 → LINE 推播"""
    print("[daily_report] 開始生成每日摘要…")
    try:
        stats   = await _fetch_today_stats()
        summary = await _generate_summary(stats)
        msg     = f"📊 iDiving 每日客服摘要\n{'─'*20}\n{summary}"
        await _push_line(msg)
        print(f"[daily_report] 完成，摘要長度={len(summary)}")
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
