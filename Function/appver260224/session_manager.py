# app/session_manager.py
# ============================================================
# 對話狀態機核心邏輯
# 所有狀態轉移都透過這裡，不要在 routes 裡直接寫 UPDATE tickets
# ============================================================

from fastapi import HTTPException

# ── 允許的狀態轉移表 ─────────────────────────────────────────
VALID_TRANSITIONS: dict[str, list[str]] = {
    "new":         ["waiting", "in_progress", "closed"],
    "waiting":     ["in_progress", "closed"],
    "in_progress": ["collecting", "booking", "closed"],
    "collecting":  ["in_progress", "booking", "closed"],
    "booking":     ["in_progress", "closed"],
    "closed":      ["new"],
}

# 狀態對應的中文說明（給前端顯示用）
STATUS_LABEL: dict[str, str] = {
    "new":         "新訊息",
    "waiting":     "等待客服",
    "in_progress": "服務中",
    "collecting":  "資料收集中",
    "booking":     "報名/預約中",
    "closed":      "已結案",
}


def get_ticket_current_status(conn, ticket_id: int) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_status FROM tickets WHERE id=%s LIMIT 1",
            (ticket_id,)
        )
        row = cur.fetchone()
    return (row["current_status"] if row else "new")


def transition_ticket_status(
    conn,
    ticket_id:    int,
    new_status:   str,
    triggered_by: str = "system",   # customer / staff / system
    staff_id:     int | None = None,
    note:         str | None = None,
):
    """
    變更 ticket 狀態：
      1. 更新 tickets.current_status
      2. 寫入 conversation_sessions 歷史記錄
    注意：呼叫端負責 commit
    """
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tickets SET current_status=%s, updated_at=NOW() WHERE id=%s",
            (new_status, ticket_id)
        )
        cur.execute(
            """
            INSERT INTO conversation_sessions
              (ticket_id, status, triggered_by, staff_id, note, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            (ticket_id, new_status, triggered_by, staff_id, note)
        )


def validate_transition(current: str, new_status: str):
    """
    驗證狀態轉移是否合法，不合法直接 raise HTTPException
    """
    allowed = VALID_TRANSITIONS.get(current, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"不允許從 '{STATUS_LABEL.get(current, current)}' "
                   f"轉換到 '{STATUS_LABEL.get(new_status, new_status)}'，"
                   f"目前允許：{[STATUS_LABEL.get(s, s) for s in allowed]}"
        )


def on_customer_message(conn, ticket_id: int):
    """
    收到客戶訊息時呼叫：自動推進狀態
      new     → waiting  （有新訊息，等待客服接手）
      closed  → new      （已結案再來訊，視為新對話開始）
      其他狀態不自動改變（由客服手動操作）
    注意：呼叫端負責 commit
    """
    current = get_ticket_current_status(conn, ticket_id)

    if current == "new":
        transition_ticket_status(
            conn, ticket_id,
            new_status="waiting",
            triggered_by="customer",
        )
    elif current == "closed":
        # 結案後又來訊息，重新開啟
        transition_ticket_status(
            conn, ticket_id,
            new_status="new",
            triggered_by="customer",
            note="客戶重新發訊，自動重開"
        )
    # in_progress / collecting / booking / waiting → 不動，只更新時間戳
