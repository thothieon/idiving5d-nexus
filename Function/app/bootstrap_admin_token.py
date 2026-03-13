# -*- coding: utf-8 -*-
# bootstrap_admin_token.py  ── idiving5d-OctoFlow v260310
#
# 用法：
#   python bootstrap_admin_token.py --staff-id 1 --label bootstrap
#
# 執行後會印出 RAW_TOKEN，把它放到 X-Admin-Token header 使用。
import argparse
import asyncio

import aiomysql

from security_staff_tokens import generate_admin_token, sha256_hex, token_prefix


# ── DB 設定（直接讀環境變數，或 fallback 到預設值）─────────────────────────
import os
DB_HOST     = os.environ.get("DB_HOST",     "192.168.12.58")
DB_PORT     = int(os.environ.get("DB_PORT", "3306"))
DB_USER     = os.environ.get("DB_USER",     "adminuser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "adminpwd")
DB_NAME     = os.environ.get("DB_NAME",     "iDiving_Line")


async def _insert_token(staff_id: int, label: str) -> str:
    raw = generate_admin_token()
    h   = sha256_hex(raw)
    pfx = token_prefix(raw)

    conn = await aiomysql.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        db=DB_NAME, charset="utf8mb4",
        cursorclass=aiomysql.DictCursor,
        autocommit=False,
    )
    try:
        async with conn.cursor() as cur:
            # 確認 staff 是否存在
            await cur.execute(
                "SELECT id, role, is_active FROM staff WHERE id=%s LIMIT 1",
                (staff_id,),
            )
            s = await cur.fetchone()
            if not s:
                raise RuntimeError(f"staff_id={staff_id} 不存在 staff 表")

            await cur.execute(
                """
                INSERT INTO staff_tokens
                  (staff_id, token_hash, token_prefix, label, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (staff_id, h, pfx, label),
            )
        await conn.commit()
    except Exception:
        await conn.rollback()
        conn.close()
        raise
    conn.close()
    return raw, pfx, h


def main():
    ap = argparse.ArgumentParser(
        description="在 staff_tokens 表新增一組 admin token"
    )
    ap.add_argument("--staff-id", type=int, required=True,
                    help="要綁定的 admin staff_id（staff 表的 id）")
    ap.add_argument("--label", type=str, default="bootstrap",
                    help="token 備註標籤（可選）")
    args = ap.parse_args()

    raw, pfx, h = asyncio.run(_insert_token(args.staff_id, args.label))

    print("✅ INSERT OK")
    print("RAW_TOKEN =", raw)   # 這個值要保存，用於呼叫 /admin/api/... 的 header
    print("PREFIX    =", pfx)
    print("TOKEN_HASH=", h)


if __name__ == "__main__":
    main()
