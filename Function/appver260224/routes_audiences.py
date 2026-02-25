# app/routes_audiences.py
# ============================================================
# 修改清單：
#   問題四：run_to_zero 改為背景執行緒，不再阻塞 HTTP worker
#   問題五：廢除 _detect_basic_information_columns()
#          改成直接操作 customers 表（固定欄位名稱）
#   問題二：移除本地 get_conn()，改從 app.db import
# ============================================================
import os
import threading
import time
import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import List

from app.db import get_conn                                       # ← 改這裡
from app.auth_staff import get_current_staff, require_admin_staff

router = APIRouter()

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()

# ── 背景任務狀態（問題四）──────────────────────────────────
_RUN_LOCK = threading.Lock()
_RUN_STATE: dict = {
    "running": False,
    "started_at": None,
    "ended_at": None,
    "elapsed_sec": 0.0,
    "batches_done": 0,
    "total_ok": 0,
    "total_fail": 0,
    "message": "idle",
    "last_batch": {},
}


class RetryBody(BaseModel):
    user_ids: List[str]


# ── LINE API helpers ─────────────────────────────────────────

def _line_headers():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="LINE_CHANNEL_ACCESS_TOKEN missing")
    return {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}


def fetch_followers_ids(max_pages: int = 10) -> list[str]:
    user_ids: list[str] = []
    start = None
    for _ in range(max_pages):
        params = {"limit": 300}
        if start:
            params["start"] = start
        r = requests.get("https://api.line.me/v2/bot/followers/ids",
                         headers=_line_headers(), params=params, timeout=15)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"followers/ids failed: {r.status_code} {r.text}")
        data = r.json() or {}
        user_ids.extend([x for x in (data.get("userIds") or []) if x])
        start = data.get("next")
        if not start:
            break
    seen = set(); out = []
    for x in user_ids:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def fetch_group_members(group_id: str) -> list[str]:
    ids: list[str] = []; start = None
    for _ in range(50):
        params = {"limit": 300}
        if start: params["start"] = start
        r = requests.get(f"https://api.line.me/v2/bot/group/{group_id}/members/ids",
                         headers=_line_headers(), params=params, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json() or {}
        ids.extend([x for x in (data.get("memberIds") or []) if x])
        start = data.get("next")
        if not start: break
    return list(dict.fromkeys(ids))


def fetch_room_members(room_id: str) -> list[str]:
    ids: list[str] = []; start = None
    for _ in range(50):
        params = {"limit": 300}
        if start: params["start"] = start
        r = requests.get(f"https://api.line.me/v2/bot/room/{room_id}/members/ids",
                         headers=_line_headers(), params=params, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json() or {}
        ids.extend([x for x in (data.get("memberIds") or []) if x])
        start = data.get("next")
        if not start: break
    return list(dict.fromkeys(ids))


def get_profile(user_id: str) -> tuple[dict, str | None, str | None]:
    r = requests.get(f"https://api.line.me/v2/bot/profile/{user_id}",
                     headers=_line_headers(), timeout=15)
    if r.status_code == 200:  return (r.json() or {}), None, None
    if r.status_code == 404:  return {}, "not_found",    "profile not found"
    if r.status_code == 403:  return {}, "forbidden",    "forbidden"
    if r.status_code == 429:  return {}, "rate_limited", "rate limited"
    return {}, f"http_{r.status_code}", (r.text or "")[:200]


# ── customers 表操作（問題五：固定欄位，不再動態偵測）────────

def ensure_customer(conn, line_user_id: str) -> int:
    """
    確保 customers 裡有這個 line_user_id，沒有就建立。
    回傳 customers.id
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM customers WHERE line_user_id=%s LIMIT 1", (line_user_id,))
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur.execute(
            "INSERT INTO customers (line_user_id, created_at, updated_at) VALUES (%s, NOW(), NOW())",
            (line_user_id,),
        )
        return int(cur.lastrowid)


def upsert_customer_profile(conn, line_user_id: str, profile: dict):
    """
    把 LINE profile 資料寫入 customers（display_name, picture_url）
    """
    display_name = profile.get("displayName")
    picture_url  = profile.get("pictureUrl")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO customers (line_user_id, display_name, picture_url, profile_synced_at,
                                   profile_status, profile_fail_count, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), 'ok', 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                display_name      = VALUES(display_name),
                picture_url       = VALUES(picture_url),
                profile_synced_at = NOW(),
                profile_status    = 'ok',
                profile_fail_count = 0,
                updated_at        = NOW()
            """,
            (line_user_id, display_name, picture_url),
        )


def mark_profile_failure(conn, line_user_id: str, code: str, msg: str):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE customers
            SET profile_status     = %s,
                profile_last_error = %s,
                profile_fail_count = profile_fail_count + 1,
                updated_at         = NOW()
            WHERE line_user_id = %s
            """,
            ((code or "unknown"), (msg or "")[:255], line_user_id),
        )


def collect_group_room_ids_from_db(conn) -> tuple[list[str], list[str]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT channel_type, channel_id FROM conversations "
            "WHERE channel_type IN ('group','room') AND channel_id IS NOT NULL AND channel_id <> ''"
        )
        rows = cur.fetchall()
    group_ids = list(dict.fromkeys(r["channel_id"] for r in rows if r["channel_type"] == "group"))
    room_ids  = list(dict.fromkeys(r["channel_id"] for r in rows if r["channel_type"] == "room"))
    return group_ids, room_ids


# ── 背景任務主體（問題四）───────────────────────────────────

def _run_to_zero_bg(batch_size: int, sleep_ms: int, max_batches: int,
                    max_seconds: int, fail_rate_threshold: float):
    """
    在背景執行緒跑。不 raise HTTPException，改印 log。
    """
    started_at = time.time()
    total_ok = 0; total_fail = 0; batches = 0
    _RUN_STATE.update({
        "running": True, "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ended_at": None, "elapsed_sec": 0.0, "batches_done": 0,
        "total_ok": 0, "total_fail": 0, "message": "running", "last_batch": {},
    })
    try:
        while True:
            elapsed = time.time() - started_at
            _RUN_STATE["elapsed_sec"] = round(elapsed, 2)
            if elapsed > max_seconds:
                _RUN_STATE["message"] = "stopped: max_seconds reached"; break
            if batches >= max_batches:
                _RUN_STATE["message"] = "stopped: max_batches reached"; break

            conn = get_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) AS n FROM customers "
                        "WHERE line_user_id IS NOT NULL AND (display_name IS NULL OR display_name='')"
                    )
                    remaining = int(cur.fetchone()["n"])
                    if remaining <= 0:
                        _RUN_STATE["message"] = "done: remaining is 0"; break

                    cur.execute(
                        "SELECT line_user_id FROM customers "
                        "WHERE line_user_id IS NOT NULL AND (display_name IS NULL OR display_name='') "
                        "AND (profile_fail_count < 3 OR profile_fail_count IS NULL) "
                        "AND (profile_status IS NULL OR profile_status NOT IN ('not_found','forbidden')) "
                        "ORDER BY updated_at ASC LIMIT %s",
                        (batch_size,),
                    )
                    targets = [r["line_user_id"] for r in cur.fetchall()]

                ok_cnt = 0; fail_cnt = 0; failed_samples = []
                for uid in targets:
                    prof, err_code, err_msg = get_profile(uid)
                    if prof:
                        upsert_customer_profile(conn, uid, prof); ok_cnt += 1
                    else:
                        fail_cnt += 1
                        mark_profile_failure(conn, uid, err_code or "unknown", err_msg or "")
                        if len(failed_samples) < 10: failed_samples.append(uid)
                        if err_code == "rate_limited": time.sleep(0.3)
                    if sleep_ms: time.sleep(sleep_ms / 1000.0)

                conn.commit()
                batches += 1; total_ok += ok_cnt; total_fail += fail_cnt
                batch_total = len(targets)
                batch_fail_rate = (fail_cnt / batch_total) if batch_total else 0.0

                _RUN_STATE.update({
                    "batches_done": batches, "total_ok": total_ok, "total_fail": total_fail,
                    "last_batch": {
                        "targets": batch_total, "ok": ok_cnt, "fail": fail_cnt,
                        "fail_rate": round(batch_fail_rate, 4),
                        "failed_samples": failed_samples,
                        "remaining_before": remaining,
                        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                })
                if batch_fail_rate >= fail_rate_threshold:
                    sleep_ms = min(500, max(1, int(sleep_ms * 1.5)))
                    _RUN_STATE["message"] = f"running (high fail rate, sleep={sleep_ms}ms)"
            finally:
                conn.close()
    except Exception as e:
        _RUN_STATE["message"] = f"error: {e}"
        print("[ERROR] run_to_zero_bg:", e)
    finally:
        _RUN_STATE["running"]  = False
        _RUN_STATE["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _RUN_STATE["elapsed_sec"] = round(time.time() - started_at, 2)
        _RUN_LOCK.release()


# ── Endpoints ────────────────────────────────────────────────

@router.get("/audiences")
def audiences_collect(
    staff: dict = Depends(get_current_staff),
    max_pages: int = Query(default=5, ge=1, le=20),
    expand_groups: bool = Query(default=True),
    expand_rooms:  bool = Query(default=True),
    max_group_room: int = Query(default=50, ge=0, le=300),
):
    require_admin_staff(staff)
    followers = fetch_followers_ids(max_pages=max_pages)

    conn = get_conn()
    try:
        group_ids, room_ids = collect_group_room_ids_from_db(conn)
        group_ids = group_ids[:max_group_room]
        room_ids  = room_ids[:max_group_room]

        group_members = [m for gid in group_ids for m in fetch_group_members(gid)] if expand_groups else []
        room_members  = [m for rid in room_ids  for m in fetch_room_members(rid)]  if expand_rooms  else []

        seen = set(); all_ids = []
        for x in followers + group_members + room_members:
            if x and x not in seen:
                seen.add(x); all_ids.append(x)

        inserted = 0
        for uid in all_ids:
            try:
                ensure_customer(conn, uid); inserted += 1
            except Exception:
                continue
        conn.commit()

        return {
            "ok": True,
            "counts": {
                "followers": len(followers),
                "group_ids": len(group_ids), "room_ids": len(room_ids),
                "group_members": len(set(group_members)), "room_members": len(set(room_members)),
                "unique_total": len(all_ids), "upserted_customers": inserted,
            },
            "sample": all_ids[:10],
        }
    finally:
        conn.close()


@router.get("/audiences/status")
def audiences_status(staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM customers WHERE line_user_id IS NOT NULL")
            total = int(cur.fetchone()["n"])

            cur.execute("SELECT COUNT(*) AS n FROM customers WHERE line_user_id IS NOT NULL "
                        "AND (display_name IS NULL OR display_name='')")
            missing = int(cur.fetchone()["n"])

            cur.execute("SELECT COUNT(*) AS n FROM customers WHERE line_user_id IS NOT NULL "
                        "AND updated_at >= CURDATE()")
            updated_today = int(cur.fetchone()["n"])

        suggested_batch    = min(300, missing)
        suggested_sleep_ms = 150 if updated_today < 20 else 80

        return {
            "ok": True,
            "total_customers": total,
            "missing_profile": missing,
            "ready_profile":   total - missing,
            "updated_today":   updated_today,
            "suggested": {"batch": suggested_batch, "sleep_ms": suggested_sleep_ms},
        }
    finally:
        conn.close()


@router.post("/audiences/profiles")
def audiences_profiles(
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=50, ge=1, le=300),
    sleep_ms: int = Query(default=50, ge=0, le=500),
):
    """單批補齊 LINE profile（同步，小批用）"""
    require_admin_staff(staff)
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT line_user_id FROM customers "
                "WHERE line_user_id IS NOT NULL AND (display_name IS NULL OR display_name='') "
                "AND (profile_fail_count < 3 OR profile_fail_count IS NULL) "
                "ORDER BY updated_at ASC LIMIT %s",
                (limit,),
            )
            targets = [r["line_user_id"] for r in cur.fetchall()]

        ok_cnt = 0; fail_cnt = 0; failed_samples = []
        for uid in targets:
            prof, err_code, err_msg = get_profile(uid)
            if prof:
                upsert_customer_profile(conn, uid, prof); ok_cnt += 1
            else:
                fail_cnt += 1
                mark_profile_failure(conn, uid, err_code or "unknown", err_msg or "")
                if len(failed_samples) < 10: failed_samples.append(uid)
                if err_code == "rate_limited": time.sleep(0.3)
            if sleep_ms: time.sleep(sleep_ms / 1000.0)

        conn.commit()
        total = len(targets)
        return {
            "ok": True, "targets": total, "ok_count": ok_cnt, "fail_count": fail_cnt,
            "fail_rate": round(fail_cnt / total, 4) if total else 0.0,
            "failed_samples": failed_samples,
        }
    finally:
        conn.close()


@router.post("/audiences/profiles/run_to_zero")
def audiences_profiles_run_to_zero(
    staff: dict = Depends(get_current_staff),
    batch_size: int = Query(default=300, ge=10, le=300),
    sleep_ms: int = Query(default=80, ge=0, le=500),
    max_batches: int = Query(default=50, ge=1, le=500),
    max_seconds: int = Query(default=600, ge=30, le=3600),
    fail_rate_threshold: float = Query(default=0.25, ge=0.0, le=1.0),
):
    """
    ✅ 問題四修正：改為背景執行緒，立即回傳 202 Accepted。
    進度請用 GET /audiences/profiles/run_state 查詢。
    """
    require_admin_staff(staff)

    if not _RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="already running, check /run_state")

    # 啟動背景執行緒
    t = threading.Thread(
        target=_run_to_zero_bg,
        args=(batch_size, sleep_ms, max_batches, max_seconds, fail_rate_threshold),
        daemon=True,
    )
    t.start()

    return {
        "ok": True,
        "message": "background task started",
        "poll_url": "/admin/api/audiences/profiles/run_state",
    }


@router.get("/audiences/profiles/run_state")
def audiences_profiles_run_state(staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    return {"ok": True, "state": dict(_RUN_STATE)}


@router.post("/audiences/profiles/retry_failed")
def audiences_profiles_retry_failed(
    body: RetryBody,
    staff: dict = Depends(get_current_staff),
    sleep_ms: int = Query(default=120, ge=0, le=500),
):
    require_admin_staff(staff)
    conn = get_conn()
    try:
        ok_cnt = 0; fail_cnt = 0; failed = []
        for uid in body.user_ids[:300]:
            prof, err_code, err_msg = get_profile(uid)
            if prof:
                upsert_customer_profile(conn, uid, prof); ok_cnt += 1
            else:
                fail_cnt += 1
                mark_profile_failure(conn, uid, err_code or "unknown", err_msg or "")
                failed.append({"user_id": uid, "code": err_code, "msg": err_msg})
            if sleep_ms: time.sleep(sleep_ms / 1000.0)
        conn.commit()
        return {"ok": True, "ok_count": ok_cnt, "fail_count": fail_cnt, "failed": failed[:10]}
    finally:
        conn.close()
