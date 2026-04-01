# app/routes_payment.py  ── Line@v260306
# ============================================================
# 繳費訂單後台管理 API
#
# main.py 加上：
#   from app.routes_payment import router as payment_router
#   app.include_router(payment_router, prefix="/admin/api")
#
# Endpoints：
#   POST   /admin/api/tickets/{ticket_id}/payment          建立訂單並推送繳費指示
#   GET    /admin/api/tickets/{ticket_id}/payment          查詢該 ticket 的訂單列表
#   GET    /admin/api/payment/orders/{order_id}            取得單筆訂單（含回填記錄）
#   PUT    /admin/api/payment/orders/{order_id}/cancel     取消訂單
#   PUT    /admin/api/payment/orders/{order_id}/verify     手動確認已收款
#   GET    /admin/api/payment/transfers                    最近回填記錄（可篩選狀態）
# ============================================================
import os
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db import get_conn
from app.auth_staff import get_current_staff, require_admin_staff
from app.payment_handler import (
    build_payment_instruction, _push_text, _push_with_quick_reply,
    ATM_BANK_CODE_DEFAULT, ATM_BANK_NAME_DEFAULT,
    ATM_ACCOUNT_NAME_DEFAULT, ATM_ACCOUNT_DEFAULT, LINE_LIFF_URL,
)

ATM_BANK_CODE = os.environ.get("ATM_BANK_CODE", "822")
ATM_ACCOUNT   = os.environ.get("ATM_ACCOUNT",   "")

router = APIRouter()


# ── Pydantic Models ──────────────────────────────────────────

class PaymentOrderCreate(BaseModel):
    amount:           int                    # 應繳金額（元）
    description:      Optional[str] = None  # 課程/品項說明
    atm_bank_code:    Optional[str] = None  # 留空則用環境變數預設值
    atm_bank_name:    Optional[str] = None  # 銀行名稱，留空用預設
    atm_account_name: Optional[str] = None  # 戶名，留空用預設
    atm_account:      Optional[str] = None  # 留空則用環境變數預設值
    due_date:         Optional[date] = None # 繳費期限

class PaymentOrderVerify(BaseModel):
    note: Optional[str] = None

class PaymentOrderCancel(BaseModel):
    note: Optional[str] = None


# ── 工具函式 ─────────────────────────────────────────────────

async def _get_ticket_and_conversation(conn, ticket_id: int):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT t.id AS ticket_id, t.conversation_id,
                   c.channel_id, c.channel_type,
                   COALESCE(cu_d.id, cu_s.id) AS customer_id
            FROM tickets t
            JOIN conversations c ON c.id = t.conversation_id
            LEFT JOIN customers cu_d ON cu_d.line_user_id = c.channel_id
                                     AND c.channel_type = 'user'
            LEFT JOIN customers cu_s ON cu_s.line_user_id = t.last_sender_user_id
                                     AND c.channel_type IN ('group', 'room')
            WHERE t.id = %s LIMIT 1
            """,
            (ticket_id,),
        )
        return await cur.fetchone()


# ── Endpoints ────────────────────────────────────────────────

@router.post("/tickets/{ticket_id}/payment")
async def create_payment_order(
    ticket_id: int,
    body: PaymentOrderCreate,
    staff: dict = Depends(get_current_staff),
):
    """
    建立繳費訂單，並透過 LINE push 傳送繳費指示給客人。
    """
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="amount 必須大於 0")

    bank_code    = (body.atm_bank_code    or ATM_BANK_CODE_DEFAULT    or "").strip()
    bank_name    = (body.atm_bank_name    or ATM_BANK_NAME_DEFAULT    or "").strip()
    account_name = (body.atm_account_name or ATM_ACCOUNT_NAME_DEFAULT or "").strip()
    account      = (body.atm_account      or ATM_ACCOUNT_DEFAULT      or "").strip()

    if not account:
        raise HTTPException(
            status_code=400,
            detail="atm_account 未填且環境變數 ATM_ACCOUNT 未設定",
        )

    async with get_conn() as conn:
        info = await _get_ticket_and_conversation(conn, ticket_id)
        if not info:
            raise HTTPException(status_code=404, detail="ticket not found")

        conversation_id = int(info["conversation_id"])
        channel_id      = (info.get("channel_id") or "").strip()
        customer_id     = info.get("customer_id")
        staff_id        = int(staff["staff_id"])

        due_str = str(body.due_date) if body.due_date else None

        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO payment_orders
                  (ticket_id, conversation_id, customer_id,
                   amount, description, atm_bank_code, atm_account,
                   due_date, status, created_by, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, NOW(), NOW())
                """,
                (
                    ticket_id, conversation_id, customer_id,
                    body.amount,
                    (body.description or "").strip() or None,
                    bank_code, account,
                    due_str,
                    staff_id,
                ),
            )
            order_id = cur.lastrowid
        await conn.commit()

    # 推送繳費指示 + Quick Reply LIFF 按鈕給客人
    if channel_id:
        instruction = build_payment_instruction({
            "amount":           body.amount,
            "description":      body.description,
            "atm_bank_code":    bank_code,
            "atm_bank_name":    bank_name,
            "atm_account_name": account_name,
            "atm_account":      account,
            "due_date":         due_str,
        })
        await _push_with_quick_reply(channel_id, instruction, LINE_LIFF_URL)

    return {"ok": True, "order_id": order_id}


@router.get("/tickets/{ticket_id}/payment")
async def list_ticket_payment_orders(
    ticket_id: int,
    staff: dict = Depends(get_current_staff),
):
    """列出 ticket 底下所有繳費訂單"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, amount, description, atm_bank_code, atm_account,
                       due_date, status, created_by, verified_at, created_at, updated_at
                FROM payment_orders
                WHERE ticket_id = %s
                ORDER BY id DESC
                """,
                (ticket_id,),
            )
            rows = await cur.fetchall()
    return {"ok": True, "items": rows}


@router.get("/payment/orders/{order_id}")
async def get_payment_order(
    order_id: int,
    staff: dict = Depends(get_current_staff),
):
    """取得單筆訂單詳情，包含對應的回填記錄"""
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, ticket_id, conversation_id, customer_id,
                       amount, description, atm_bank_code, atm_account,
                       due_date, status, created_by, verified_at, created_at, updated_at
                FROM payment_orders WHERE id = %s LIMIT 1
                """,
                (order_id,),
            )
            order = await cur.fetchone()

        if not order:
            raise HTTPException(status_code=404, detail="order not found")

        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, transfer_last5, reported_amount, raw_text,
                       match_status, created_at
                FROM payment_transfers
                WHERE payment_order_id = %s
                ORDER BY id DESC
                """,
                (order_id,),
            )
            transfers = await cur.fetchall()

    return {"ok": True, "order": order, "transfers": transfers}


@router.put("/payment/orders/{order_id}/verify")
async def manually_verify_order(
    order_id: int,
    body: PaymentOrderVerify,
    staff: dict = Depends(get_current_staff),
):
    """手動標記訂單為已收款（客服確認用）"""
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, status FROM payment_orders WHERE id = %s LIMIT 1",
                (order_id,),
            )
            order = await cur.fetchone()

        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        if order["status"] == "verified":
            raise HTTPException(status_code=409, detail="already verified")
        if order["status"] == "cancelled":
            raise HTTPException(status_code=409, detail="order is cancelled")

        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE payment_orders "
                "SET status='verified', verified_at=NOW(), updated_at=NOW() "
                "WHERE id=%s",
                (order_id,),
            )
        await conn.commit()
    return {"ok": True}


@router.put("/payment/orders/{order_id}/cancel")
async def cancel_order(
    order_id: int,
    body: PaymentOrderCancel,
    staff: dict = Depends(get_current_staff),
):
    """取消繳費訂單"""
    require_admin_staff(staff)
    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT id, status FROM payment_orders WHERE id = %s LIMIT 1",
                (order_id,),
            )
            order = await cur.fetchone()

        if not order:
            raise HTTPException(status_code=404, detail="order not found")
        if order["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"cannot cancel, current status: {order['status']}")

        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE payment_orders SET status='cancelled', updated_at=NOW() WHERE id=%s",
                (order_id,),
            )
        await conn.commit()
    return {"ok": True}


@router.get("/payment/transfers")
async def list_transfers(
    staff: dict = Depends(get_current_staff),
    match_status: Optional[str] = Query(default=None, description="matched / unmatched"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """列出最近的客人繳費回填記錄"""
    conditions = []
    params     = []

    if match_status in ("matched", "unmatched"):
        conditions.append("pt.match_status = %s")
        params.append(match_status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    async with get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT pt.id, pt.payment_order_id, pt.conversation_id, pt.ticket_id,
                       pt.transfer_last5, pt.reported_amount, pt.raw_text,
                       pt.match_status, pt.created_at,
                       po.amount AS order_amount, po.description
                FROM payment_transfers pt
                LEFT JOIN payment_orders po ON po.id = pt.payment_order_id
                {where}
                ORDER BY pt.id DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = await cur.fetchall()

    return {"ok": True, "items": rows, "limit": limit, "offset": offset}
