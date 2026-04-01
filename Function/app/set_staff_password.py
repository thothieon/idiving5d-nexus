#!/usr/bin/env python3
# set_staff_password.py  ── idiving5d-OctoFlow
#
# 用法：
#   python set_staff_password.py --staff-id 1 --username admin --password 你的密碼
#   python set_staff_password.py --staff-id 2 --username staff01 --password 你的密碼
#
import argparse
import asyncio
import os

import aiomysql
import bcrypt

DB_HOST     = os.environ.get("DB_HOST",     "192.168.12.58")
DB_PORT     = int(os.environ.get("DB_PORT", "3306"))
DB_USER     = os.environ.get("DB_USER",     "adminuser")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "adminpwd")
DB_NAME     = os.environ.get("DB_NAME",     "iDiving_Line")


async def set_password(staff_id: int, username: str, password: str):
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    conn = await aiomysql.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        db=DB_NAME, charset="utf8mb4",
        cursorclass=aiomysql.DictCursor,
        autocommit=False,
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id, name, role FROM staff WHERE id=%s", (staff_id,))
            row = await cur.fetchone()
            if not row:
                print(f"[ERROR] staff_id={staff_id} 不存在")
                return

            await cur.execute(
                "UPDATE staff SET username=%s, password_hash=%s WHERE id=%s",
                (username, hashed, staff_id),
            )
        await conn.commit()
        print(f"[OK] staff_id={staff_id} name={row['name']} role={row['role']}")
        print(f"     username={username}  password 已設定")
    except Exception as e:
        await conn.rollback()
        print(f"[ERROR] {e}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="設定員工登入帳號密碼")
    parser.add_argument("--staff-id", type=int, required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    asyncio.run(set_password(args.staff_id, args.username, args.password))


if __name__ == "__main__":
    main()
