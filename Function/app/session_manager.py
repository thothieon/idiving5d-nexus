# app/session_manager.py  ── idiving5d-OctoFlow v260310
# ============================================================
# 對話狀態機核心邏輯（全面 async）
# ============================================================
from fastapi import HTTPException

VALID_TRANSITIONS: dict[str, list[str]] = {
    "new":         ["waiting", "in_progress", "closed"],
    "waiting":     ["in_progress", "closed"],
    "in_progress": ["collecting", "booking", "closed"],
    "collecting":  ["in_progress", "booking", "closed"],
    "booking":     ["in_progress", "closed"],
    "closed":      ["new"],
}

STATUS_LABEL: dict[str, str] = {
    "new":         "新訊息",
    "waiting":     "等待客服",
    "in_progress": "服務中",
    "collecting":  "資料收集中",
    "booking":     "報名/預約中",
    "closed":      "已結案",
}


# 查詢指定 ticket 目前的狀態，查無資料則預設為 "new"
async def get_ticket_current_status(conn, ticket_id: int) -> str:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT current_status FROM tickets WHERE id=%s LIMIT 1",
            (ticket_id,)
        )
        row = await cur.fetchone()
    return (row["current_status"] if row else "new")


# 變更 ticket 狀態並寫入 conversation_sessions 歷史記錄，呼叫端需自行 commit
async def transition_ticket_status(
    conn,
    ticket_id:    int,
    new_status:   str,
    triggered_by: str = "system",
    staff_id:     int | None = None,
    note:         str | None = None,
):
    """
    變更 ticket 狀態：
      1. 更新 tickets.current_status
      2. 寫入 conversation_sessions 歷史記錄
    注意：呼叫端負責 commit
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE tickets SET current_status=%s, updated_at=NOW() WHERE id=%s",
            (new_status, ticket_id)
        )
        await cur.execute(
            """
            INSERT INTO conversation_sessions
              (ticket_id, status, triggered_by, staff_id, note, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (ticket_id, new_status, triggered_by, staff_id, note)
        )


# 同步驗證狀態轉換是否合法，不合法直接拋出 400 錯誤
def validate_transition(current: str, new_status: str):
    """同步檢查，不合法直接 raise HTTPException"""
    allowed = VALID_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不允許從 '{STATUS_LABEL.get(current, current)}' "
                   f"轉換到 '{STATUS_LABEL.get(new_status, new_status)}'，"
                   f"目前允許：{[STATUS_LABEL.get(s, s) for s in allowed]}"
        )


# 收到客戶訊息時呼叫，自動將 ticket 狀態推進（new→waiting、closed→new）
async def on_customer_message(conn, ticket_id: int):
    """
    收到客戶訊息時呼叫：自動推進狀態
    注意：呼叫端負責 commit
    """
    current = await get_ticket_current_status(conn, ticket_id)

    if current == "new":
        await transition_ticket_status(
            conn, ticket_id,
            new_status="waiting",
            triggered_by="customer",
        )
    elif current == "closed":
        await transition_ticket_status(
            conn, ticket_id,
            new_status="new",
            triggered_by="customer",
            note="客戶重新發訊，自動重開"
        )
