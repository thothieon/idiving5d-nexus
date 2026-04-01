# app/routes_liff.py  ── Line@v260320
# ============================================================
# LIFF 匯款回報 API（無需 staff token，以 LINE idToken 驗證身份）
#
# main.py 加上：
#   from app.routes_liff import router as liff_router
#   app.include_router(liff_router, prefix="/liff")
#
# Endpoints：
#   POST /liff/payment/orders   取得此 LINE 用戶的 pending 訂單列表
#   POST /liff/payment/submit   提交匯款末五碼+金額，自動比對核銷
# ============================================================
import os
import httpx
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import get_conn
from app.payment_handler import _push_text

LINE_CHANNEL_ID = os.environ.get("LINE_CHANNEL_ID", "")

router = APIRouter()


# ── LIFF idToken 驗證 ─────────────────────────────────────────

async def verify_liff_token(id_token: str) -> Optional[str]:
    """
    向 LINE 驗證 LIFF idToken，回傳 line_user_id（sub）。
    驗證失敗回傳 None。
    """
    if not id_token or not LINE_CHANNEL_ID:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.line.me/oauth2/v2.1/verify",
                data={"id_token": id_token, "client_id": LINE_CHANNEL_ID},
            )
        if r.status_code == 200:
            return r.json().get("sub")  # sub = LINE userId
    except Exception as e:
        print(f"[WARN] liff token verify error: {e}")
    return None


# ── Pydantic Models ──────────────────────────────────────────

class LiffTokenBody(BaseModel):
    id_token: str


class LiffSubmitBody(BaseModel):
    id_token: str
    order_id: int
    last5:    str   # 匯款帳號末五碼
    amount:   int   # 客人填寫金額


# ── Endpoints ────────────────────────────────────────────────

@router.post("/payment/orders")
async def liff_get_pending_orders(body: LiffTokenBody):
    """
    取得此 LINE 用戶所有 pending 的繳費訂單。
    LIFF 頁面初始化後呼叫，讓客人選擇要回報哪一筆。
    """
    line_user_id = await verify_liff_token(body.id_token)
    if not line_user_id:
        raise HTTPException(status_code=401, detail="invalid LIFF token")

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT po.id, po.amount, po.description,
                       po.atm_bank_code, po.atm_account,
                       po.due_date, po.conversation_id, po.created_at
                FROM payment_orders po
                JOIN conversations c ON c.id = po.conversation_id
                WHERE c.channel_type = 'user'
                  AND c.channel_id   = %s
                  AND po.status      = 'pending'
                ORDER BY po.id DESC
                """,
                (line_user_id,),
            )
            orders = await cur.fetchall()

    return {"ok": True, "items": orders}


@router.post("/payment/submit")
async def liff_submit_transfer(body: LiffSubmitBody):
    """
    客人在 LIFF 填寫末五碼+金額後呼叫。
    1. 驗證 LIFF idToken 取得 line_user_id
    2. 確認 order_id 屬於此用戶
    3. 比對金額
    4. 寫入 payment_transfers
    5. 自動核銷（金額符合）或推送提示
    """
    # 驗證身份
    line_user_id = await verify_liff_token(body.id_token)
    if not line_user_id:
        raise HTTPException(status_code=401, detail="invalid LIFF token")

    # 驗證末五碼格式
    last5 = (body.last5 or "").strip()
    if len(last5) != 5 or not last5.isdigit():
        raise HTTPException(status_code=400, detail="末五碼必須為 5 位數字")

    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="金額必須大於 0")

    match_status     = "unmatched"
    matched_order_id = None
    reply_text       = ""
    channel_id       = None
    ticket_id        = None

    async with get_conn() as conn:
        # 查詢訂單，同時確認屬於此用戶
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT po.id, po.amount, po.description, po.status,
                       po.conversation_id, po.ticket_id,
                       c.channel_id, c.channel_type
                FROM payment_orders po
                JOIN conversations c ON c.id = po.conversation_id
                WHERE po.id          = %s
                  AND c.channel_type = 'user'
                  AND c.channel_id   = %s
                LIMIT 1
                """,
                (body.order_id, line_user_id),
            )
            order = await cur.fetchone()

        if not order:
            raise HTTPException(status_code=404, detail="找不到對應的繳費訂單")

        if order["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail="此訂單已完成或已取消，無需重複回報",
            )

        channel_id = (order.get("channel_id") or "").strip()
        ticket_id  = order.get("ticket_id")
        order_amount = int(order["amount"])
        desc = (order.get("description") or "").strip()

        if order_amount == body.amount:
            # ── 金額符合，自動核銷 ─────────────────────────
            match_status     = "matched"
            matched_order_id = order["id"]

            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE payment_orders "
                    "SET status='verified', verified_at=NOW(), updated_at=NOW() "
                    "WHERE id=%s",
                    (order["id"],),
                )

            reply_text = (
                f"✅ 匯款確認完成！\n\n"
                f"{'課程：' + desc + chr(10) if desc else ''}"
                f"轉帳末五碼：{last5}\n"
                f"金額：{body.amount:,} 元\n\n"
                f"感謝您的付款，我們已收到您的匯款，"
                f"報名程序已完成！如有任何問題歡迎隨時聯繫我們 🤿"
            )
        else:
            # ── 金額不符，等人工確認 ──────────────────────
            reply_text = (
                f"⚠️ 金額對應不符\n\n"
                f"您填寫的金額為 {body.amount:,} 元，\n"
                f"但應繳金額為 {order_amount:,} 元。\n\n"
                f"請確認後重新回報，或聯繫客服協助處理。"
            )

        # 寫入轉帳記錄
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO payment_transfers
                  (payment_order_id, conversation_id, ticket_id,
                   transfer_last5, reported_amount, raw_text,
                   liff_user_id, match_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    matched_order_id,
                    order["conversation_id"],
                    ticket_id,
                    last5,
                    body.amount,
                    f"LIFF 回報 末五碼:{last5} 金額:{body.amount}",
                    line_user_id,
                    match_status,
                ),
            )
        await conn.commit()

    # 推送 LINE 訊息
    if channel_id:
        await _push_text(channel_id, reply_text)

    return {
        "ok":           True,
        "match_status": match_status,
        "message":      reply_text,
    }
