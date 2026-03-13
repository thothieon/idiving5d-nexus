# app/routes_crawler.py  ── idiving5d-OctoFlow v260310
# 負責：
#   POST /internal/crawler/snapshot  → 儲存課程快照到 MySQL
#   GET  /internal/crawler/last_hash → 取得某課程最新一筆 hash（供比對是否有變更）
#
# 認證：呼叫方須在 body（POST）或 query string（GET）帶 token=CRAWLER_SECRET
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_conn

router = APIRouter()

# 從環境變數讀取，和 docker-crawler/.env 的 CRAWLER_SECRET 對應
CRAWLER_SECRET = os.environ.get("CRAWLER_SECRET", "")


# ── 建表 DDL（首次呼叫時自動建立，之後 IF NOT EXISTS 不重複建） ──────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS divessi_course_snapshots (
    id           BIGINT       AUTO_INCREMENT PRIMARY KEY,
    course_name  VARCHAR(100) NOT NULL,
    course_url   TEXT         NOT NULL,
    content_hash VARCHAR(64)  NOT NULL,
    content      LONGTEXT,
    page_count   INT          DEFAULT 0,
    char_count   INT          DEFAULT 0,
    is_changed   TINYINT(1)   DEFAULT 0,
    crawled_at   DATETIME     NOT NULL,
    INDEX idx_course_name (course_name),
    INDEX idx_crawled_at  (crawled_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


# ── Request schema ────────────────────────────────────────────────────────────
class SnapshotIn(BaseModel):
    token:        str
    course_name:  str
    course_url:   str
    content_hash: str
    content:      str
    page_count:   int
    char_count:   int
    is_changed:   bool


# ── POST /internal/crawler/snapshot ──────────────────────────────────────────
@router.post("/crawler/snapshot")
async def save_snapshot(body: SnapshotIn):
    """儲存一筆課程快照。checker.py 每次爬取後呼叫一次。"""
    if not CRAWLER_SECRET or body.token != CRAWLER_SECRET:
        raise HTTPException(status_code=403, detail="Bad token")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(CREATE_TABLE_SQL)
            await cur.execute(
                """
                INSERT INTO divessi_course_snapshots
                    (course_name, course_url, content_hash, content,
                     page_count, char_count, is_changed, crawled_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    body.course_name, body.course_url, body.content_hash,
                    body.content, body.page_count, body.char_count,
                    1 if body.is_changed else 0, now,
                ),
            )
        await conn.commit()

    return {"ok": True, "course_name": body.course_name, "crawled_at": now}


# ── GET /internal/crawler/last_hash ──────────────────────────────────────────
@router.get("/crawler/last_hash")
async def get_last_hash(course_name: str, token: str):
    """取得某課程最新一筆 content_hash，供 checker.py 比對是否有變更。"""
    if not CRAWLER_SECRET or token != CRAWLER_SECRET:
        raise HTTPException(status_code=403, detail="Bad token")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            # 確保資料表存在（首次執行時）
            await cur.execute(CREATE_TABLE_SQL)
            await cur.execute(
                """
                SELECT content_hash FROM divessi_course_snapshots
                WHERE course_name = %s
                ORDER BY crawled_at DESC
                LIMIT 1
                """,
                (course_name,),
            )
            row = await cur.fetchone()
        # READ-ONLY：不需 commit，直接返回
    return {"hash": row["content_hash"] if row else None}
