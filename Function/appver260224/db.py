# app/db.py  ── Line@v260306
# ============================================================
# 全面改為 async aiomysql 連線池
# 啟動時由 main.py lifespan 呼叫 init_db_pool()
# 所有 routes 改用：async with get_conn() as conn:
# ============================================================
import os
import aiomysql
from contextlib import asynccontextmanager

DB_HOST     = os.environ.get("DB_HOST",     "192.168.12.159")
DB_PORT     = int(os.environ.get("DB_PORT", "3306"))
DB_USER     = os.environ.get("DB_USER",     "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "rootpwd")
DB_NAME     = os.environ.get("DB_NAME",     "iDiving_Line")

_pool: aiomysql.Pool | None = None


async def init_db_pool():
    """在 app 啟動時呼叫一次，建立全域連線池"""
    global _pool
    _pool = await aiomysql.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        db=DB_NAME,
        charset="utf8mb4",
        cursorclass=aiomysql.DictCursor,
        autocommit=False,
        minsize=3,
        maxsize=20,
    )


async def close_db_pool():
    """在 app 關閉時呼叫，釋放連線池"""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


@asynccontextmanager
async def get_conn():
    """
    使用方式：
        async with get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT ...")
                rows = await cur.fetchall()
            await conn.commit()

    例外時自動 rollback，離開 context 自動歸還連線池。
    """
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_db_pool() first.")
    async with _pool.acquire() as conn:
        try:
            yield conn
        except Exception:
            await conn.rollback()
            raise
