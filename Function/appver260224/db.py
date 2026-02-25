# app/db.py
# ============================================================
# 統一 DB 連線入口
# 所有 routes_*.py 和 auth_staff.py 都從這裡 import get_conn
# 不要再各自定義！
# ============================================================
import os
import pymysql

DB_HOST     = os.environ.get("DB_HOST", "192.168.12.159")
DB_PORT     = int(os.environ.get("DB_PORT", "3306"))
DB_USER     = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "rootpwd")
DB_NAME     = os.environ.get("DB_NAME", "iDiving_Line")


def get_conn() -> pymysql.connections.Connection:
    """
    取得一條 pymysql 連線（手動管理 commit/rollback/close）
    使用方式：
        conn = get_conn()
        try:
            ...
            conn.commit()
        except:
            conn.rollback()
            raise
        finally:
            conn.close()
    """
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
