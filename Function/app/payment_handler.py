# app/payment_handler.py  ── Line@v260306
# ============================================================
# 繳費比對核心邏輯
#
# 流程：
#   1. 客服後台建立 payment_order（含 ATM 帳號、金額）
#      → 系統推送繳費指示（含銀行資訊）+ Quick Reply LIFF 按鈕
#   2. 客人點「我已匯款」→ 開啟 LIFF 頁面填寫末五碼+金額
#   3. LIFF 呼叫 /liff/payment/submit，後端比對
#      → 金額符合：標記 verified，推送確認訊息
#      → 金額不符：推送提示，請重新確認
#      → 查無訂單：推送提示，請聯繫客服
# ============================================================
import re
import os
import httpx

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_LIFF_URL             = os.environ.get("LINE_LIFF_URL", "https://liff.line.me/2009420432-ZWrRUmas")

ATM_BANK_CODE_DEFAULT    = os.environ.get("ATM_BANK_CODE",    "822")
ATM_BANK_NAME_DEFAULT    = os.environ.get("ATM_BANK_NAME",    "中國信託 士林分行")
ATM_ACCOUNT_NAME_DEFAULT = os.environ.get("ATM_ACCOUNT_NAME", "愛潛水股份有限公司")
ATM_ACCOUNT_DEFAULT      = os.environ.get("ATM_ACCOUNT",      "")

# ── 解析客人回填格式 ─────────────────────────────────────────
#
# 支援格式（容錯設計）：
#   後五碼：12345 金額：3000
#   後5碼12345，金額3000元
#   末五碼：12345，金額：3,000
#   尾五碼 12345 金額 3000 元
#   轉帳末五碼：12345 金額：3000
#
_LAST5_RE = re.compile(
    r'(?:後|末|尾)(?:五|5)碼[：:\s]*(\d{5})',
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r'金額[：:\s]*([\d,，]+)',
    re.IGNORECASE,
)


def parse_transfer_reply(text: str) -> dict | None:
    """
    嘗試從客人訊息中解析末五碼與金額。
    回傳 {"last5": "12345", "amount": 3000} 或 None（無法解析）。
    """
    text = (text or "").strip()
    if not text:
        return None

    m_last5  = _LAST5_RE.search(text)
    m_amount = _AMOUNT_RE.search(text)

    if not m_last5 or not m_amount:
        return None

    last5 = m_last5.group(1).strip()
    amount_str = m_amount.group(1).replace(",", "").replace("，", "").strip()

    try:
        amount = int(amount_str)
    except ValueError:
        return None

    if len(last5) != 5 or amount <= 0:
        return None

    return {"last5": last5, "amount": amount}


# ── 繳費回填處理主函式 ────────────────────────────────────────

async def handle_payment_transfer(
    channel_id:      str,
    conversation_id: int,
    ticket_id:       int,
    transfer_info:   dict,
    raw_text:        str,
):
    """
    1. 取得該 conversation 下最新的 pending 訂單
    2. 比對金額
    3. 寫入 payment_transfers
    4. 推送 LINE 回應
    呼叫端已 commit，此函式自行管理 DB。
    """
    from app.db import get_conn

    last5  = transfer_info["last5"]
    amount = transfer_info["amount"]

    matched_order_id = None
    match_status     = "unmatched"
    reply_text       = ""

    async with get_conn() as conn:
        # 查詢該 conversation 最新的 pending 訂單
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, amount, description, atm_account
                FROM payment_orders
                WHERE conversation_id = %s AND status = 'pending'
                ORDER BY id DESC LIMIT 1
                """,
                (conversation_id,),
            )
            order = await cur.fetchone()

        if order and int(order["amount"]) == amount:
            # ── 金額符合，標記完成 ─────────────────────────
            matched_order_id = order["id"]
            match_status     = "matched"

            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE payment_orders "
                    "SET status='verified', verified_at=NOW(), updated_at=NOW() "
                    "WHERE id=%s",
                    (order["id"],),
                )

            desc = (order.get("description") or "").strip()
            reply_text = (
                f"✅ 訂金確認完成！\n\n"
                f"{'課程：' + desc + chr(10) if desc else ''}"
                f"轉帳末五碼：{last5}\n"
                f"金額：{amount:,} 元\n\n"
                f"感謝您的付款，我們已收到您的訂金，"
                f"報名程序已完成！如有任何問題歡迎隨時聯繫我們 🤿"
            )

        elif order:
            # ── 金額不符 ──────────────────────────────────
            expect = int(order["amount"])
            reply_text = (
                f"⚠️ 金額對應不符\n\n"
                f"您填寫的金額為 {amount:,} 元，\n"
                f"但應繳金額為 {expect:,} 元。\n\n"
                f"請確認後重新回填，格式如下：\n"
                f"後五碼：XXXXX\n金額：{expect:,}\n\n"
                f"若有疑問請聯繫客服協助處理。"
            )

        else:
            # ── 查無待繳訂單 ──────────────────────────────
            reply_text = (
                f"⚠️ 查無待繳款項\n\n"
                f"目前查無您的待繳款記錄，\n"
                f"請聯繫客服確認繳費資訊。"
            )

        # 寫入轉帳記錄
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO payment_transfers
                  (payment_order_id, conversation_id, ticket_id,
                   transfer_last5, reported_amount, raw_text, match_status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    matched_order_id, conversation_id, ticket_id,
                    last5, amount, raw_text, match_status,
                ),
            )
        await conn.commit()

    # 推送 LINE 訊息
    await _push_text(channel_id, reply_text)


# ── LINE push helpers ─────────────────────────────────────────

async def _push_text(channel_id: str, text: str):
    if not LINE_CHANNEL_ACCESS_TOKEN or not channel_id:
        return
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.line.me/v2/bot/message/push",
                headers=headers,
                json={"to": channel_id, "messages": [{"type": "text", "text": text}]},
            )
        if r.status_code != 200:
            print(f"[WARN] payment push failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[WARN] payment push error: {e}")


async def _push_with_quick_reply(channel_id: str, text: str, liff_url: str):
    """推送帶有 Quick Reply LIFF 按鈕的繳費通知"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not channel_id:
        return
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    message = {
        "type": "text",
        "text": text,
        "quickReply": {
            "items": [
                {
                    "type": "action",
                    "action": {
                        "type":  "uri",
                        "label": "✅ 我已匯款，點此回報",
                        "uri":   liff_url,
                    },
                }
            ]
        },
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.line.me/v2/bot/message/push",
                headers=headers,
                json={"to": channel_id, "messages": [message]},
            )
        if r.status_code != 200:
            print(f"[WARN] payment push (quick reply) failed: {r.status_code} {r.text}")
    except Exception as e:
        print(f"[WARN] payment push (quick reply) error: {e}")


# ── 推送繳費指示給客人（建立訂單時呼叫）────────────────────────

def build_payment_instruction(order: dict) -> str:
    """
    組裝發給客人的繳費說明文字（含完整銀行資訊）。
    order 欄位：amount, description, atm_bank_code, atm_bank_name,
               atm_account_name, atm_account, due_date
    """
    desc         = (order.get("description")     or "").strip()
    amount       = int(order.get("amount", 0))
    bank_code    = (order.get("atm_bank_code")    or ATM_BANK_CODE_DEFAULT).strip()
    bank_name    = (order.get("atm_bank_name")    or ATM_BANK_NAME_DEFAULT).strip()
    account_name = (order.get("atm_account_name") or ATM_ACCOUNT_NAME_DEFAULT).strip()
    account      = (order.get("atm_account")      or "").strip()
    due_date     = order.get("due_date")

    lines = ["💰 繳費通知"]
    if desc:
        lines.append(f"課程／品項：{desc}")
    lines.append(f"應繳金額：{amount:,} 元")
    if due_date:
        lines.append(f"繳費期限：{due_date}")

    lines += [
        "",
        "【匯款資訊】",
        f"銀行代號：{bank_code}",
        f"銀　　行：{bank_name}",
        f"戶　　名：{account_name}",
        f"帳　　號：{account}",
        "",
        "匯款完成後，請點下方按鈕回報匯款資訊 👇",
    ]
    return "\n".join(lines)
