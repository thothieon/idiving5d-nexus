# -*- coding: utf-8 
# bootstrap_admin_token.py
# -*- coding: utf-8 -*-
import argparse

from security_staff_tokens import generate_admin_token, sha256_hex, token_prefix
from db import get_conn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staff-id", type=int, required=True, help="要綁定的 admin staff_id（staff 表的 id）")
    ap.add_argument("--label", type=str, default="bootstrap", help="token label（可選）")
    args = ap.parse_args()

    raw = generate_admin_token()
    h = sha256_hex(raw)
    pfx = token_prefix(raw)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # 建議順便檢查 staff 是否存在（可選，但很有幫助）
            cur.execute("SELECT id, role, is_active FROM staff WHERE id=%s LIMIT 1", (args.staff_id,))
            s = cur.fetchone()
            if not s:
                raise RuntimeError(f"staff_id={args.staff_id} 不存在於 staff 表")
            # 你要更嚴格也可以檢查 role/is_active
            # if s.get("role") != "admin" or int(s.get("is_active") or 0) != 1:
            #     raise RuntimeError(f"staff_id={args.staff_id} 不是 active admin: {s}")

            cur.execute(
                """
                INSERT INTO staff_tokens (staff_id, token_hash, token_prefix, label, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                """,
                (args.staff_id, h, pfx, args.label),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("? INSERT OK")
    print("RAW_TOKEN =", raw)   # 這把要保存好（之後打 /admin/api/... 用它）
    print("PREFIX    =", pfx)
    print("TOKEN_HASH=", h)


if __name__ == "__main__":
    main()

