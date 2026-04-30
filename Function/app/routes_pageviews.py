# app/routes_pageviews.py  ── idiving5d-OctoFlow
# ============================================================
# 官網頁面瀏覽分析
#
# Public（官網呼叫，無需驗證）:
#   POST /api/pv              記錄一次頁面瀏覽，回傳 pv_id
#   POST /api/pv/leave        更新停留時間
#   POST /api/pv/heartbeat    保持即時在線狀態
#
# Admin（需 X-Admin-Token）:
#   GET /admin/api/stats/pageviews            頁面排行（含跳出率）
#   GET /admin/api/stats/pageviews/daily      每日趨勢
#   GET /admin/api/stats/pageviews/referrers  來源排行
#   GET /admin/api/stats/pageviews/devices    裝置類型
#   GET /admin/api/stats/pageviews/sessions   連續行為路徑
#   GET /admin/api/stats/pageviews/online     即時在線人數
# ============================================================
import re

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from typing import Optional

from app.db import get_conn
from app.auth_staff import get_current_staff

# ── DDL ─────────────────────────────────────────────────────
_CREATE_PAGE_VIEWS_SQL = """
CREATE TABLE IF NOT EXISTS page_views (
    id           BIGINT       AUTO_INCREMENT PRIMARY KEY,
    session_id   VARCHAR(64)  NOT NULL DEFAULT '',
    page_path    VARCHAR(200) NOT NULL,
    referrer     VARCHAR(500),
    ip_addr      VARCHAR(50),
    user_agent   VARCHAR(500),
    device_type  VARCHAR(10),
    duration_sec INT,
    visited_at   DATETIME     NOT NULL,
    INDEX idx_session    (session_id),
    INDEX idx_page_path  (page_path),
    INDEX idx_visited_at (visited_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_CREATE_HEARTBEATS_SQL = """
CREATE TABLE IF NOT EXISTS page_heartbeats (
    session_id VARCHAR(64)  NOT NULL,
    page_path  VARCHAR(200) NOT NULL DEFAULT '',
    last_seen  DATETIME     NOT NULL,
    PRIMARY KEY (session_id),
    INDEX idx_last_seen (last_seen)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_CREATE_PAGE_EVENTS_SQL = """
CREATE TABLE IF NOT EXISTS page_events (
    id          BIGINT       AUTO_INCREMENT PRIMARY KEY,
    pv_id       BIGINT,
    session_id  VARCHAR(64)  NOT NULL DEFAULT '',
    event_type  VARCHAR(50)  NOT NULL,
    label       VARCHAR(200),
    page        VARCHAR(200),
    created_at  DATETIME     NOT NULL,
    INDEX idx_pe_session    (session_id),
    INDEX idx_pe_event_type (event_type),
    INDEX idx_pe_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

# 為舊版資料表補欄位（欄位已存在時靜默忽略）
_MIGRATIONS = [
    "ALTER TABLE page_views ADD COLUMN session_id   VARCHAR(64)  NOT NULL DEFAULT ''",
    "ALTER TABLE page_views ADD COLUMN user_agent   VARCHAR(500)",
    "ALTER TABLE page_views ADD COLUMN device_type  VARCHAR(10)",
    "ALTER TABLE page_views ADD COLUMN duration_sec INT",
    "CREATE INDEX idx_session ON page_views (session_id)",
]

_tables_ready = False

public_router = APIRouter()
admin_router  = APIRouter()


# ── 建表 / 遷移 ──────────────────────────────────────────────
async def _ensure_tables():
    global _tables_ready
    if _tables_ready:
        return
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_CREATE_PAGE_VIEWS_SQL)
            await cur.execute(_CREATE_HEARTBEATS_SQL)
            await cur.execute(_CREATE_PAGE_EVENTS_SQL)
            for sql in _MIGRATIONS:
                try:
                    await cur.execute(sql)
                except Exception:
                    pass  # 欄位/索引已存在則忽略
        await conn.commit()
    _tables_ready = True


# ── 裝置判斷 ─────────────────────────────────────────────────
def _detect_device(ua: str) -> str:
    u = (ua or "").lower()
    if re.search(r'mobile|android|iphone|ipod|windows phone|blackberry', u):
        return 'mobile'
    if re.search(r'ipad|tablet', u):
        return 'tablet'
    return 'desktop'


# ── Request schemas ──────────────────────────────────────────
class PageViewIn(BaseModel):
    page:       str
    ref:        Optional[str] = None
    session_id: Optional[str] = None
    ua:         Optional[str] = None


class LeaveIn(BaseModel):
    pv_id:        int
    duration_sec: int


class HeartbeatIn(BaseModel):
    session_id: str
    page:       str


class EventIn(BaseModel):
    pv_id:      Optional[int] = None
    session_id: Optional[str] = None
    type:       str                    # e.g. 'cta_signup', 'nav_signup', 'outbound_line'
    label:      Optional[str] = None   # 觸發來源頁路徑
    page:       Optional[str] = None   # 同 label，前端兩者都送


# ── 真實 IP 提取（Cloudflare Tunnel → nginx → FastAPI）────────
def _get_real_ip(request: Request) -> str | None:
    # Cloudflare Tunnel 帶 CF-Connecting-IP（訪客真實 IP）
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    # nginx proxy_set_header X-Forwarded-For 最左邊是訪客 IP
    xfwd = request.headers.get("x-forwarded-for")
    if xfwd:
        return xfwd.split(",")[0].strip()
    # 最後 fallback
    return request.client.host if request.client else None


# ── POST /api/pv ─────────────────────────────────────────────
@public_router.post("/pv")
async def record_page_view(body: PageViewIn, request: Request):
    await _ensure_tables()

    page_path   = (body.page or "/").strip()[:200]
    referrer    = (body.ref        or "").strip()[:500] or None
    session_id  = (body.session_id or "").strip()[:64]  or ""
    ua          = (body.ua or request.headers.get("user-agent", ""))[:500]
    ip_addr     = _get_real_ip(request)
    device_type = _detect_device(ua)

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO page_views
                  (session_id, page_path, referrer, ip_addr, user_agent, device_type, visited_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                """,
                (session_id, page_path, referrer, ip_addr, ua, device_type),
            )
            pv_id = cur.lastrowid
        await conn.commit()

    return {"ok": True, "pv_id": pv_id}


# ── POST /api/pv/event ──────────────────────────────────────
@public_router.post("/pv/event")
async def record_event(body: EventIn):
    await _ensure_tables()

    event_type = (body.type  or "").strip()[:50]
    label      = (body.label or body.page or "").strip()[:200] or None
    page       = (body.page  or "").strip()[:200] or None
    session_id = (body.session_id or "").strip()[:64] or ""

    if not event_type:
        return {"ok": False, "error": "type required"}

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO page_events
                  (pv_id, session_id, event_type, label, page, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                """,
                (body.pv_id, session_id, event_type, label, page),
            )
        await conn.commit()

    return {"ok": True}


# ── POST /api/pv/leave ───────────────────────────────────────
@public_router.post("/pv/leave")
async def record_leave(body: LeaveIn):
    await _ensure_tables()
    dur = max(0, min(body.duration_sec, 86400))
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE page_views SET duration_sec=%s WHERE id=%s AND duration_sec IS NULL",
                (dur, body.pv_id),
            )
        await conn.commit()
    return {"ok": True}


# ── POST /api/pv/heartbeat ───────────────────────────────────
@public_router.post("/pv/heartbeat")
async def record_heartbeat(body: HeartbeatIn):
    await _ensure_tables()
    sid  = (body.session_id or "").strip()[:64]
    page = (body.page or "/").strip()[:200]
    if not sid:
        return {"ok": False}
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO page_heartbeats (session_id, page_path, last_seen)
                VALUES (%s, %s, NOW())
                ON DUPLICATE KEY UPDATE page_path=VALUES(page_path), last_seen=NOW()
                """,
                (sid, page),
            )
        await conn.commit()
    return {"ok": True}


# ── GET /admin/api/stats/pageviews ───────────────────────────
# 頁面排行：瀏覽數、不重複 IP、平均停留時間、跳出率
@admin_router.get("/stats/pageviews")
async def stats_pageviews(
    days:  int = Query(7,   ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    staff: dict = Depends(get_current_staff),
):
    await _ensure_tables()
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    pv.page_path,
                    COUNT(*)                    AS views,
                    COUNT(DISTINCT pv.ip_addr)  AS uniques,
                    ROUND(AVG(pv.duration_sec)) AS avg_duration,
                    ROUND(
                        100.0 * SUM(CASE WHEN s.page_count = 1 THEN 1 ELSE 0 END)
                        / NULLIF(COUNT(CASE WHEN pv.session_id != '' THEN 1 END), 0)
                    ) AS bounce_pct
                FROM page_views pv
                LEFT JOIN (
                    SELECT session_id, COUNT(*) AS page_count
                    FROM page_views
                    WHERE visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                      AND session_id != ''
                    GROUP BY session_id
                ) s ON s.session_id = pv.session_id AND pv.session_id != ''
                WHERE pv.visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY pv.page_path
                ORDER BY views DESC
                LIMIT %s
            """, (days, days, limit))
            rows = await cur.fetchall()

            await cur.execute(
                "SELECT COUNT(*) AS total FROM page_views "
                "WHERE visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)",
                (days,)
            )
            total = (await cur.fetchone())["total"]

    return {"ok": True, "days": days, "total": total, "items": rows}


# ── GET /admin/api/stats/pageviews/daily ─────────────────────
@admin_router.get("/stats/pageviews/daily")
async def stats_pageviews_daily(
    days:  int = Query(30, ge=1, le=365),
    staff: dict = Depends(get_current_staff),
):
    await _ensure_tables()
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    DATE(visited_at)           AS date,
                    COUNT(*)                   AS views,
                    COUNT(DISTINCT ip_addr)    AS uniques
                FROM page_views
                WHERE visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY DATE(visited_at)
                ORDER BY date ASC
            """, (days,))
            rows = await cur.fetchall()

    items = [{"date": str(r["date"]), "views": r["views"], "uniques": r["uniques"]}
             for r in rows]
    return {"ok": True, "days": days, "items": items}


# ── GET /admin/api/stats/pageviews/referrers ─────────────────
@admin_router.get("/stats/pageviews/referrers")
async def stats_referrers(
    days:  int = Query(7,  ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
    staff: dict = Depends(get_current_staff),
):
    await _ensure_tables()
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    COALESCE(NULLIF(TRIM(referrer), ''), '（直接流量）') AS referrer,
                    COUNT(*) AS views
                FROM page_views
                WHERE visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY page_views.referrer
                ORDER BY views DESC
                LIMIT %s
            """, (days, limit))
            rows = await cur.fetchall()

    return {"ok": True, "items": rows}


# ── GET /admin/api/stats/pageviews/devices ───────────────────
@admin_router.get("/stats/pageviews/devices")
async def stats_devices(
    days:  int = Query(7, ge=1, le=365),
    staff: dict = Depends(get_current_staff),
):
    await _ensure_tables()
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    COALESCE(NULLIF(device_type,''), 'desktop') AS device_type,
                    COUNT(*) AS views
                FROM page_views
                WHERE visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY page_views.device_type
                ORDER BY views DESC
            """, (days,))
            rows = await cur.fetchall()

    return {"ok": True, "items": rows}


# ── GET /admin/api/stats/pageviews/sessions ──────────────────
@admin_router.get("/stats/pageviews/sessions")
async def stats_sessions(
    days:  int = Query(7,  ge=1, le=90),
    limit: int = Query(30, ge=1, le=100),
    staff: dict = Depends(get_current_staff),
):
    await _ensure_tables()
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    session_id,
                    COUNT(*)  AS page_count,
                    MIN(visited_at) AS start_at,
                    TIMESTAMPDIFF(SECOND, MIN(visited_at), MAX(visited_at)) AS duration_sec,
                    GROUP_CONCAT(page_path ORDER BY visited_at SEPARATOR ' → ') AS journey
                FROM page_views
                WHERE visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                  AND session_id != ''
                GROUP BY session_id
                HAVING page_count > 1
                ORDER BY page_count DESC, duration_sec DESC
                LIMIT %s
            """, (days, limit))
            rows = await cur.fetchall()

    items = [{
        "session_id":   r["session_id"],
        "page_count":   r["page_count"],
        "start_at":     str(r["start_at"]),
        "duration_sec": r["duration_sec"] or 0,
        "journey":      (r["journey"] or "")[:300],
    } for r in rows]
    return {"ok": True, "items": items}


# ── GET /admin/api/stats/pageviews/online ────────────────────
@admin_router.get("/stats/pageviews/online")
async def stats_online(staff: dict = Depends(get_current_staff)):
    await _ensure_tables()
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM page_heartbeats
                WHERE last_seen >= DATE_SUB(NOW(), INTERVAL 2 MINUTE)
            """)
            online = (await cur.fetchone())["cnt"]

            await cur.execute("""
                SELECT page_path, COUNT(*) AS cnt
                FROM page_heartbeats
                WHERE last_seen >= DATE_SUB(NOW(), INTERVAL 2 MINUTE)
                GROUP BY page_path
                ORDER BY cnt DESC
                LIMIT 10
            """)
            pages = await cur.fetchall()

    return {"ok": True, "online": online, "pages": pages}


# ── GET /admin/api/stats/pageviews/events ────────────────────
# CTA 點擊排行：各事件類型 × 來源頁面的點擊次數
@admin_router.get("/stats/pageviews/events")
async def stats_events(
    days:       int = Query(7,   ge=1, le=365),
    event_type: str = Query("",  description="篩選特定 type，空白=全部"),
    limit:      int = Query(100, ge=1, le=500),
    staff: dict = Depends(get_current_staff),
):
    await _ensure_tables()

    type_filter = f"AND event_type = %s" if event_type else ""
    params = [days]
    if event_type:
        params.append(event_type)
    params.append(limit)

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(f"""
                SELECT
                    event_type,
                    COALESCE(NULLIF(label, ''), '（未知頁面）') AS label,
                    COUNT(*)                                     AS clicks,
                    COUNT(DISTINCT session_id)                   AS sessions
                FROM page_events
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                  {type_filter}
                GROUP BY event_type, label
                ORDER BY clicks DESC
                LIMIT %s
            """, params)
            rows = await cur.fetchall()

    return {"ok": True, "days": days, "items": rows}


# ── GET /admin/api/stats/pageviews/funnel ────────────────────
# 漏斗轉換率：各課程頁 → 立即報名 的轉換率
# 計算方式：
#   - 分母：該頁面的不重複 session 瀏覽數（page_views）
#   - 分子：從該頁面按下 cta_signup 的不重複 session 數（page_events）
@admin_router.get("/stats/pageviews/funnel")
async def stats_funnel(
    days:  int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    staff: dict = Depends(get_current_staff),
):
    await _ensure_tables()
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                SELECT
                    pv.page_path                                       AS page,
                    COUNT(DISTINCT pv.session_id)                      AS visitors,
                    COUNT(DISTINCT pe.session_id)                      AS signups,
                    ROUND(
                        100.0 * COUNT(DISTINCT pe.session_id)
                        / NULLIF(COUNT(DISTINCT pv.session_id), 0)
                    )                                                  AS conversion_pct
                FROM page_views pv
                LEFT JOIN page_events pe
                    ON  pe.session_id  = pv.session_id
                    AND pe.event_type  = 'cta_signup'
                    AND pe.label       = pv.page_path
                    AND pe.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                WHERE pv.visited_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                  AND pv.session_id != ''
                  AND pv.page_path NOT IN ('/', '#/')
                GROUP BY pv.page_path
                HAVING visitors >= 5
                ORDER BY signups DESC, conversion_pct DESC
                LIMIT %s
            """, (days, days, limit))
            rows = await cur.fetchall()

    return {"ok": True, "days": days, "items": rows}
