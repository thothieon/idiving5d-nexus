# app/routes_linestats.py  ── idiving5d-OctoFlow
# ================================================================
# LINE 客服後台使用量分析
#
# GET  /admin/api/stats/line/overview       總覽數字
# GET  /admin/api/stats/line/daily          每日趨勢（訊息、工單、客戶）
# GET  /admin/api/stats/line/peak_hours     尖峰時段分析
# GET  /admin/api/stats/line/tickets        工單狀態與處理時長
# GET  /admin/api/stats/line/intents        意圖分佈
# GET  /admin/api/stats/line/message_types  訊息類型分佈
# GET  /admin/api/stats/line/courses        課程熱度排行
# POST /admin/api/stats/line/daily_report   手動觸發每日摘要推播
# ================================================================
import asyncio
from fastapi import APIRouter, Depends, Query
from app.db import get_conn
from app.auth_staff import get_current_staff

router = APIRouter()


# ── 總覽 ─────────────────────────────────────────────────────

@router.get("/stats/line/overview")
async def line_overview(
    days: int = Query(7, ge=1, le=365),
    staff: dict = Depends(get_current_staff),
):
    """總覽卡片：今日 / 近 N 日的核心數字"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:

            # 今日訊息數（客人傳入）
            await cur.execute("""
                SELECT COUNT(*) AS cnt FROM messages_raw
                WHERE direction='in' AND DATE(created_at)=CURDATE()
            """)
            today_msgs_in = (await cur.fetchone())["cnt"]

            # 今日客服回覆數
            await cur.execute("""
                SELECT COUNT(*) AS cnt FROM messages_raw
                WHERE direction='out' AND sender_type='staff' AND DATE(created_at)=CURDATE()
            """)
            today_msgs_out = (await cur.fetchone())["cnt"]

            # 今日新工單
            await cur.execute("""
                SELECT COUNT(*) AS cnt FROM tickets WHERE DATE(created_at)=CURDATE()
            """)
            today_tickets = (await cur.fetchone())["cnt"]

            # 今日新客戶
            await cur.execute("""
                SELECT COUNT(*) AS cnt FROM customers WHERE DATE(created_at)=CURDATE()
            """)
            today_customers = (await cur.fetchone())["cnt"]

            # 近 N 日訊息總量
            await cur.execute("""
                SELECT COUNT(*) AS cnt FROM messages_raw
                WHERE direction='in'
                  AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (days,))
            period_msgs_in = (await cur.fetchone())["cnt"]

            # 目前活躍工單（未結案）
            await cur.execute("""
                SELECT COUNT(*) AS cnt FROM tickets
                WHERE current_status NOT IN ('closed')
            """)
            active_tickets = (await cur.fetchone())["cnt"]

            # 近 N 日新客戶
            await cur.execute("""
                SELECT COUNT(*) AS cnt FROM customers
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (days,))
            period_customers = (await cur.fetchone())["cnt"]

            # 近 N 日結案率（closed / total opened）
            await cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN current_status='closed' THEN 1 ELSE 0 END) AS closed
                FROM tickets
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (days,))
            row = await cur.fetchone()
            total_t  = row["total"]  or 1
            closed_t = row["closed"] or 0
            close_rate = round(closed_t / total_t * 100)

    return {
        "ok":   True,
        "days": days,
        "today": {
            "msgs_in":   today_msgs_in,
            "msgs_out":  today_msgs_out,
            "tickets":   today_tickets,
            "customers": today_customers,
        },
        "period": {
            "msgs_in":       period_msgs_in,
            "active_tickets": active_tickets,
            "new_customers":  period_customers,
            "close_rate_pct": close_rate,
        },
    }


# ── 每日趨勢 ─────────────────────────────────────────────────

@router.get("/stats/line/daily")
async def line_daily(
    days: int = Query(30, ge=7, le=365),
    staff: dict = Depends(get_current_staff),
):
    """每日：客人訊息數、客服回覆數、新工單數、新客戶數"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:

            await cur.execute("""
                SELECT
                    DATE(created_at)                                  AS date,
                    SUM(direction='in')                               AS msgs_in,
                    SUM(direction='out' AND sender_type='staff')      AS msgs_out
                FROM messages_raw
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY DATE(created_at)
                ORDER BY date ASC
            """, (days,))
            msg_rows = {str(r["date"]): r for r in await cur.fetchall()}

            await cur.execute("""
                SELECT DATE(created_at) AS date, COUNT(*) AS cnt
                FROM tickets
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY DATE(created_at)
            """, (days,))
            ticket_rows = {str(r["date"]): r["cnt"] for r in await cur.fetchall()}

            await cur.execute("""
                SELECT DATE(created_at) AS date, COUNT(*) AS cnt
                FROM customers
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY DATE(created_at)
            """, (days,))
            customer_rows = {str(r["date"]): r["cnt"] for r in await cur.fetchall()}

    # 合併成統一清單（以 msg_rows 的日期為基礎）
    all_dates = sorted(set(list(msg_rows.keys()) + list(ticket_rows.keys()) + list(customer_rows.keys())))
    items = []
    for d in all_dates:
        mr = msg_rows.get(d, {})
        items.append({
            "date":      d,
            "msgs_in":   int(mr.get("msgs_in")  or 0),
            "msgs_out":  int(mr.get("msgs_out") or 0),
            "tickets":   ticket_rows.get(d, 0),
            "customers": customer_rows.get(d, 0),
        })

    return {"ok": True, "days": days, "items": items}


# ── 尖峰時段 ─────────────────────────────────────────────────

@router.get("/stats/line/peak_hours")
async def line_peak_hours(
    days: int = Query(30, ge=1, le=365),
    staff: dict = Depends(get_current_staff),
):
    """各小時（0~23）的客人訊息量，找出最忙時段"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT HOUR(created_at) AS hour, COUNT(*) AS cnt
                FROM messages_raw
                WHERE direction='in'
                  AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY HOUR(created_at)
                ORDER BY hour ASC
            """, (days,))
            rows = await cur.fetchall()

    # 補齊 0~23 全部小時
    hour_map = {r["hour"]: r["cnt"] for r in rows}
    items = [{"hour": h, "cnt": hour_map.get(h, 0)} for h in range(24)]

    return {"ok": True, "days": days, "items": items}


# ── 工單分析 ─────────────────────────────────────────────────

@router.get("/stats/line/tickets")
async def line_tickets(
    days: int = Query(30, ge=1, le=365),
    staff: dict = Depends(get_current_staff),
):
    """工單狀態分佈 + 平均處理時長（分鐘）"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:

            # 狀態分佈
            await cur.execute("""
                SELECT current_status AS status, COUNT(*) AS cnt
                FROM tickets
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY current_status
                ORDER BY cnt DESC
            """, (days,))
            status_rows = await cur.fetchall()

            # 平均處理時長（已結案工單，opened_at → 最後一次進入 closed 的時間）
            await cur.execute("""
                SELECT
                    ROUND(AVG(
                        TIMESTAMPDIFF(MINUTE, t.opened_at, cs.created_at)
                    )) AS avg_resolve_min
                FROM tickets t
                JOIN conversation_sessions cs
                    ON cs.ticket_id = t.id AND cs.status = 'closed'
                WHERE t.current_status = 'closed'
                  AND t.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (days,))
            row = await cur.fetchone()
            avg_resolve_min = row["avg_resolve_min"] if row else None

            # 平均首次回應時間（客人訊息 → 第一則客服回覆）
            await cur.execute("""
                SELECT ROUND(AVG(diff_min)) AS avg_first_reply_min
                FROM (
                    SELECT t.id,
                        TIMESTAMPDIFF(MINUTE,
                            (SELECT MIN(m1.created_at) FROM messages_raw m1
                             WHERE m1.ticket_id=t.id AND m1.direction='in'),
                            (SELECT MIN(m2.created_at) FROM messages_raw m2
                             WHERE m2.ticket_id=t.id AND m2.direction='out'
                               AND m2.sender_type='staff')
                        ) AS diff_min
                    FROM tickets t
                    WHERE t.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                ) sub
                WHERE diff_min IS NOT NULL AND diff_min >= 0 AND diff_min < 1440
            """, (days,))
            row2 = await cur.fetchone()
            avg_first_reply_min = row2["avg_first_reply_min"] if row2 else None

    status_labels = {
        "new":         "新訊息",
        "waiting":     "等待客服",
        "in_progress": "服務中",
        "collecting":  "資料收集中",
        "booking":     "報名預約中",
        "closed":      "已結案",
    }
    status_dist = [
        {"status": r["status"], "label": status_labels.get(r["status"], r["status"]), "cnt": r["cnt"]}
        for r in status_rows
    ]

    return {
        "ok":   True,
        "days": days,
        "status_dist":       status_dist,
        "avg_resolve_min":   avg_resolve_min,
        "avg_first_reply_min": avg_first_reply_min,
    }


# ── 意圖分析 ─────────────────────────────────────────────────

@router.get("/stats/line/intents")
async def line_intents(
    days: int = Query(30, ge=1, le=365),
    staff: dict = Depends(get_current_staff),
):
    """AI 分類的意圖分佈"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    COALESCE(intent, 'general') AS intent,
                    COUNT(*) AS cnt,
                    ROUND(AVG(intent_confidence)) AS avg_confidence
                FROM conversation_intakes
                WHERE updated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                  AND intent IS NOT NULL
                GROUP BY intent
                ORDER BY cnt DESC
            """, (days,))
            rows = await cur.fetchall()

    intent_labels = {
        "course_inquiry": "詢問課程",
        "booking":        "要報名",
        "payment":        "繳費相關",
        "complaint":      "抱怨反映",
        "general":        "一般閒聊",
    }
    intent_colors = {
        "course_inquiry": "#42A5F5",
        "booking":        "#66BB6A",
        "payment":        "#FFA726",
        "complaint":      "#EF5350",
        "general":        "#9E9E9E",
    }
    items = [
        {
            "intent":          r["intent"],
            "label":           intent_labels.get(r["intent"], r["intent"]),
            "color":           intent_colors.get(r["intent"], "#9E9E9E"),
            "cnt":             r["cnt"],
            "avg_confidence":  r["avg_confidence"],
        }
        for r in rows
    ]
    total = sum(i["cnt"] for i in items) or 1
    for i in items:
        i["pct"] = round(i["cnt"] / total * 100)

    return {"ok": True, "days": days, "items": items}


# ── 訊息類型 ─────────────────────────────────────────────────

@router.get("/stats/line/message_types")
async def line_message_types(
    days: int = Query(30, ge=1, le=365),
    staff: dict = Depends(get_current_staff),
):
    """客人訊息的類型分佈（text/image/sticker/video/audio/file）"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT message_type, COUNT(*) AS cnt
                FROM messages_raw
                WHERE direction='in'
                  AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY message_type
                ORDER BY cnt DESC
            """, (days,))
            rows = await cur.fetchall()

    labels = {
        "text":    "文字",
        "image":   "圖片",
        "sticker": "貼圖",
        "video":   "影片",
        "audio":   "語音",
        "file":    "檔案",
    }
    colors = {
        "text":    "#42A5F5",
        "image":   "#66BB6A",
        "sticker": "#FFA726",
        "video":   "#AB47BC",
        "audio":   "#26C6DA",
        "file":    "#8D6E63",
    }
    total = sum(r["cnt"] for r in rows) or 1
    items = [
        {
            "type":  r["message_type"],
            "label": labels.get(r["message_type"], r["message_type"]),
            "color": colors.get(r["message_type"], "#9E9E9E"),
            "cnt":   r["cnt"],
            "pct":   round(r["cnt"] / total * 100),
        }
        for r in rows
    ]
    return {"ok": True, "days": days, "items": items}


# ── 課程熱度 ─────────────────────────────────────────────────

@router.get("/stats/line/courses")
async def line_courses(
    days:  int = Query(30, ge=1, le=365),
    limit: int = Query(10, ge=1, le=50),
    staff: dict = Depends(get_current_staff),
):
    """被詢問最多的課程類型排行"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT course_type, COUNT(*) AS cnt
                FROM conversation_intakes
                WHERE course_type IS NOT NULL AND course_type != ''
                  AND updated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY course_type
                ORDER BY cnt DESC
                LIMIT %s
            """, (days, limit))
            rows = await cur.fetchall()

    total = sum(r["cnt"] for r in rows) or 1
    items = [
        {
            "course_type": r["course_type"],
            "cnt":         r["cnt"],
            "pct":         round(r["cnt"] / total * 100),
        }
        for r in rows
    ]
    return {"ok": True, "days": days, "items": items}


# ── 手動觸發每日摘要 ──────────────────────────────────────────

@router.post("/stats/line/daily_report")
async def trigger_daily_report(
    staff: dict = Depends(get_current_staff),
):
    """手動觸發每日客服摘要（立即生成並推播至 LINE）"""
    from app.daily_report import run_daily_report
    asyncio.create_task(run_daily_report())
    return {"ok": True, "message": "每日摘要生成中，約 10 秒後推播至 LINE"}
