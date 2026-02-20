# app/routes_audiences.py
import os
import threading
import time
import requests
import pymysql
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth_staff import get_current_staff, require_admin_staff

from pydantic import BaseModel
from typing import List

router = APIRouter()

_RUN_LOCK = threading.Lock()

_RUN_STATE = {
    "running": False,
    "started_at": None,
    "ended_at": None,
    "elapsed_sec": 0.0,
    "batches_done": 0,
    "max_batches": None,
    "max_seconds": None,
    "batch_size": None,
    "sleep_ms": None,
    "total_ok": 0,
    "total_fail": 0,
    "last_batch": {
        "targets": 0,
        "ok": 0,
        "fail": 0,
        "fail_rate": 0.0,
        "failed_samples": [],
        "remaining_before": None,
        "remaining_after": None,
        "finished_at": None,
    },
    "message": "",
}

# ---- ENV ----
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "").strip()

DB_HOST = os.environ.get("DB_HOST", "192.168.12.159")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "rootpwd")
DB_NAME = os.environ.get("DB_NAME", "iDiving_LineTest")

class RetryBody(BaseModel):
    user_ids: List[str]


def get_conn():
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


def _line_headers():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=500, detail="LINE_CHANNEL_ACCESS_TOKEN missing")
    return {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}


def fetch_followers_ids(max_pages: int = 10) -> list[str]:
    """
    LINE followers/insight: /v2/bot/followers/ids
    會分頁回 userIds + next
    """
    user_ids: list[str] = []
    start = None
    for _ in range(max_pages):
        url = "https://api.line.me/v2/bot/followers/ids"
        params = {"limit": 300}
        if start:
            params["start"] = start
        r = requests.get(url, headers=_line_headers(), params=params, timeout=15)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"followers/ids failed: {r.status_code} {r.text}")
        data = r.json() or {}
        ids = data.get("userIds") or []
        user_ids.extend([x for x in ids if x])
        start = data.get("next")
        if not start:
            break
    # 去重保序
    seen = set()
    out = []
    for x in user_ids:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def fetch_group_members(group_id: str) -> list[str]:
    """
    /v2/bot/group/{groupId}/members/ids 會分頁
    """
    ids: list[str] = []
    start = None
    for _ in range(50):
        url = f"https://api.line.me/v2/bot/group/{group_id}/members/ids"
        params = {"limit": 300}
        if start:
            params["start"] = start
        r = requests.get(url, headers=_line_headers(), params=params, timeout=20)
        if r.status_code != 200:
            # 不要整個炸掉，回空即可（可能 bot 不在群、權限不足）
            return []
        data = r.json() or {}
        page_ids = data.get("memberIds") or []
        ids.extend([x for x in page_ids if x])
        start = data.get("next")
        if not start:
            break
    return list(dict.fromkeys(ids))


def fetch_room_members(room_id: str) -> list[str]:
    """
    /v2/bot/room/{roomId}/members/ids 會分頁
    """
    ids: list[str] = []
    start = None
    for _ in range(50):
        url = f"https://api.line.me/v2/bot/room/{room_id}/members/ids"
        params = {"limit": 300}
        if start:
            params["start"] = start
        r = requests.get(url, headers=_line_headers(), params=params, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json() or {}
        page_ids = data.get("memberIds") or []
        ids.extend([x for x in page_ids if x])
        start = data.get("next")
        if not start:
            break
    return list(dict.fromkeys(ids))


def get_profile(user_id: str):
    url = f"https://api.line.me/v2/bot/profile/{user_id}"
    r = requests.get(url, headers=_line_headers(), timeout=15)

    if r.status_code == 200:
        return (r.json() or {}), None, None

    # 常見：404（拿不到 profile：不是好友/封鎖/失效 等情況）
    if r.status_code == 404:
        return {}, "not_found", "profile not found (often blocked/not friend/invalid)"

    # 偶爾：403（權限/情境不允許）
    if r.status_code == 403:
        return {}, "forbidden", "forbidden"

    # 429：被限流
    if r.status_code == 429:
        return {}, "rate_limited", "rate limited"

    # 其他：記錄一下
    msg = (r.text or "")[:200]
    return {}, f"http_{r.status_code}", msg



def ensure_basic_information_user(conn, user_id: str):
    """
    basic_information：如果沒有就插入（只先保證 line_user_id 存在）
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM basic_information WHERE line_user_id=%s LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur.execute(
            """
            INSERT INTO basic_information (line_user_id, created_at, updated_at)
            VALUES (%s, NOW(), NOW())
            """,
            (user_id,),
        )
        return int(cur.lastrowid)


def upsert_basic_information_profile(conn, user_id: str, profile: dict):
    """
    用 SHOW COLUMNS 自動偵測：
    - uid 欄位：user_id (你目前 DB 就是)
    - name 欄位：name
    - picture 欄位：沒有就略過
    """
    meta = _detect_basic_information_columns(conn)
    uid_col = meta["uid"]          # 你目前是 user_id
    display_col = meta["display"]  # 你目前是 name
    picture_col = meta["picture"]  # 你目前 None
    updated_col = meta["updated"]  # 你目前 updated_at

    if not uid_col:
        raise RuntimeError("basic_information uid column not found")

    display_name = profile.get("displayName")
    picture_url = profile.get("pictureUrl")

    set_parts = []
    params = []

    if display_col:
        set_parts.append(f"`{display_col}`=%s")
        params.append(display_name)

    if picture_col:
        set_parts.append(f"`{picture_col}`=%s")
        params.append(picture_url)

    if updated_col:
        set_parts.append(f"`{updated_col}`=NOW()")

    if not set_parts:
        return None

    with conn.cursor() as cur:
        # 有就 update，沒有就 insert（只塞 uid + name）
        cur.execute(f"SELECT 1 FROM basic_information WHERE `{uid_col}`=%s LIMIT 1", (user_id,))
        exists = cur.fetchone()

        if exists:
            sql = f"UPDATE basic_information SET {', '.join(set_parts)} WHERE `{uid_col}`=%s"
            cur.execute(sql, (*params, user_id))
            return True
        else:
            cols = [uid_col]
            vals = [user_id]

            if display_col:
                cols.append(display_col)
                vals.append(display_name)

            if picture_col:
                cols.append(picture_col)
                vals.append(picture_url)

            if updated_col and updated_col not in cols:
                cols.append(updated_col)
                # updated_at 如果是 timestamp/datetime 欄位，直接 NOW()
                # 但 insert 不能用參數代表 NOW()，這裡用 SQL NOW()
                sql_cols = ", ".join([f"`{c}`" for c in cols])
                placeholders = ", ".join(["%s"] * (len(cols) - 1) + ["NOW()"])
                sql = f"INSERT INTO basic_information ({sql_cols}) VALUES ({placeholders})"
                cur.execute(sql, (*vals,))
            else:
                sql_cols = ", ".join([f"`{c}`" for c in cols])
                placeholders = ", ".join(["%s"] * len(cols))
                sql = f"INSERT INTO basic_information ({sql_cols}) VALUES ({placeholders})"
                cur.execute(sql, (*vals,))
            return True

def mark_profile_failure(conn, user_id: str, code: str, msg: str, max_len: int = 255):
    meta = _detect_basic_information_columns(conn)
    uid_col = meta["uid"]
    if not uid_col:
        return

    # 注意：這些欄位是你剛剛 ALTER TABLE 加的
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE basic_information
            SET profile_status=%s,
                profile_last_error=%s,
                profile_last_try_at=NOW(),
                profile_fail_count=profile_fail_count + 1,
                updated_at=NOW()
            WHERE `{uid_col}`=%s
            """,
            (code, (msg or "")[:max_len], user_id),
        )


def collect_group_room_ids_from_db(conn) -> tuple[list[str], list[str]]:
    """
    從 DB 找出出現過的 group/room channel_id
    來源：conversations (channel_type, channel_id)
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT channel_type, channel_id
            FROM conversations
            WHERE channel_type IN ('group', 'room')
              AND channel_id IS NOT NULL
              AND channel_id <> ''
            """
        )
        rows = cur.fetchall()

    group_ids = [r["channel_id"] for r in rows if r["channel_type"] == "group"]
    room_ids = [r["channel_id"] for r in rows if r["channel_type"] == "room"]
    # 去重保序
    group_ids = list(dict.fromkeys(group_ids))
    room_ids = list(dict.fromkeys(room_ids))
    return group_ids, room_ids

def _detect_basic_information_columns(conn) -> dict:
    """
    自動偵測 basic_information 相關欄位名稱（避免你 DB 欄位叫 line_uid / line_userid / user_id 等）
    回傳 dict: {"uid": "...", "display": "...", "picture": "...", "created": "...", "updated": "..."}
    """
    with conn.cursor() as cur:
        cur.execute("SHOW COLUMNS FROM basic_information")
        cols = [r["Field"] for r in cur.fetchall()]

    s = set(cols)

    # 可能的 UID 欄位名稱候選
    uid_candidates = [
        "line_user_id", "line_uid", "line_userid", "user_id", "uid", "mid", "line_mid",
    ]
    display_candidates = ["display_name", "displayName", "name"]
    picture_candidates = ["picture_url", "pictureUrl", "avatar_url", "avatar"]
    created_candidates = ["created_at", "createdAt", "created"]
    updated_candidates = ["updated_at", "updatedAt", "updated"]

    def pick(cands):
        for c in cands:
            if c in s:
                return c
        return None

    return {
        "uid": pick(uid_candidates),
        "display": pick(display_candidates),
        "picture": pick(picture_candidates),
        "created": pick(created_candidates),
        "updated": pick(updated_candidates),
        "all": cols,
    }



@router.post("/audiences/test")
def audiences_test(staff: dict = Depends(get_current_staff)):
    require_admin_staff(staff)
    return {"ok": True, "who": staff.get("name")}


@router.get("/audiences")
def audiences_collect(
    staff: dict = Depends(get_current_staff),
    max_pages: int = Query(default=5, ge=1, le=20),
    expand_groups: bool = Query(default=True),
    expand_rooms: bool = Query(default=True),
    max_group_room: int = Query(default=50, ge=0, le=300),
):
    """
    1) followers/ids
    2) DB 內出現過的 group/room
    3) (可選) 展開群/房 members ids
    4) 把新 user_id 寫入 basic_information
    """
    require_admin_staff(staff)

    followers = fetch_followers_ids(max_pages=max_pages)

    conn = get_conn()
    try:
        group_ids, room_ids = collect_group_room_ids_from_db(conn)

        # 控制不要一次爆量
        group_ids = group_ids[:max_group_room]
        room_ids = room_ids[:max_group_room]

        group_members: list[str] = []
        room_members: list[str] = []

        if expand_groups:
            for gid in group_ids:
                group_members.extend(fetch_group_members(gid))

        if expand_rooms:
            for rid in room_ids:
                room_members.extend(fetch_room_members(rid))

        # 合併去重
        all_ids = []
        seen = set()
        for x in followers + group_members + room_members:
            if x and x not in seen:
                seen.add(x)
                all_ids.append(x)

        # 寫入 basic_information（只建立 line_user_id）
        inserted = 0
        for uid in all_ids:
            try:
                ensure_basic_information_user(conn, uid)
                inserted += 1
            except Exception:
                # 個別失敗不阻斷
                continue

        conn.commit()

        return {
            "ok": True,
            "counts": {
                "followers": len(followers),
                "group_ids": len(group_ids),
                "room_ids": len(room_ids),
                "group_members": len(set(group_members)),
                "room_members": len(set(room_members)),
                "unique_total": len(all_ids),
                "attempted_upsert_basic_information": inserted,
            },
            "sample": all_ids[:10],
        }
    finally:
        conn.close()


@router.post("/audiences/profiles")
def audiences_profiles(
    staff: dict = Depends(get_current_staff),
    limit: int = Query(default=50, ge=1, le=300),
    sleep_ms: int = Query(default=50, ge=0, le=500),
):
    require_admin_staff(staff)

    conn = get_conn()
    try:
        # 你原本已經改成動態欄位的 targets 查詢
        meta = _detect_basic_information_columns(conn)
        uid_col = meta["uid"]
        display_col = meta["display"]
        updated_col = meta["updated"]

        if not uid_col:
            raise HTTPException(status_code=500, detail="basic_information uid column not found")
        if not display_col:
            raise HTTPException(status_code=500, detail="basic_information name column not found")

        uid_where = f"`{uid_col}` IS NOT NULL AND `{uid_col}` <> ''"
        missing_name_where = f"(`{display_col}` IS NULL OR `{display_col}`='')"
        order_by = f"`{updated_col}` ASC" if updated_col else f"`{uid_col}` ASC"

        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT `{uid_col}` AS uid
                FROM basic_information
                WHERE {uid_where}
                  AND {missing_name_where}
                  AND (profile_fail_count < 3 OR profile_fail_count IS NULL)
                ORDER BY {order_by}
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

        targets = [r["uid"] for r in rows if r.get("uid")]

        ok_cnt = 0
        fail_cnt = 0
        failed_samples = []

        for uid in targets:
            prof, err_code, err_msg = get_profile(uid)
            
            if prof:
                upsert_basic_information_profile(conn, uid, prof)
                ok_cnt += 1
            else:
                fail_cnt += 1
                mark_profile_failure(conn, uid, err_code or "unknown", err_msg or "")
                
                if len(failed_samples) < 10:
                    failed_samples.append(uid)

                # 如果是 rate limit，稍微多睡一下（讓下一筆比較容易成功）
                if err_code == "rate_limited":
                    time.sleep(0.3)
                    
        conn.commit()

        total = len(targets)
        fail_rate = (fail_cnt / total) if total else 0.0

        return {
            "ok": True,
            "requested": limit,
            "targets": total,
            "ok_count": ok_cnt,
            "fail_count": fail_cnt,
            "fail_rate": round(fail_rate, 4),
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
    一鍵跑到 missing=0（或達到上限就停止）
    - batch_size: 每批最多處理幾個
    - sleep_ms: 每個 profile 請求間隔
    - max_batches / max_seconds: 保護上限
    - fail_rate_threshold: 若單批失敗率過高，自動把 sleep_ms 增加
    """
    require_admin_staff(staff)

    if not _RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="audiences run is already in progress")

    started_at = time.time()
    total_ok = 0
    total_fail = 0
    batches = 0
    last_failed_samples = []

    try:
        while True:
            if (time.time() - started_at) > max_seconds:
                break
            if batches >= max_batches:
                break

            # 每批都重新抓 missing targets
            conn = get_conn()
            try:
                meta = _detect_basic_information_columns(conn)
                uid_col = meta["uid"]
                display_col = meta["display"]
                updated_col = meta["updated"]

                if not uid_col or not display_col:
                    raise HTTPException(status_code=500, detail="basic_information uid/name column not found")

                uid_where = f"`{uid_col}` IS NOT NULL AND `{uid_col}` <> ''"
                missing_name_where = f"(`{display_col}` IS NULL OR `{display_col}`='')"
                order_by = f"`{updated_col}` ASC" if updated_col else f"`{uid_col}` ASC"

                with conn.cursor() as cur:
                    # 先看還剩多少
                    cur.execute(
                        f"SELECT COUNT(*) AS n FROM basic_information WHERE {uid_where} AND {missing_name_where}"
                    )
                    remaining = int(cur.fetchone()["n"])

                    if remaining <= 0:
                        break

                    cur.execute(
                        f"""
                        SELECT `{uid_col}` AS uid
                        FROM basic_information
                        WHERE {uid_where}
                          AND {missing_name_where}
                        ORDER BY {order_by}
                        LIMIT %s
                        """,
                        (batch_size,),
                    )
                    rows = cur.fetchall()

                targets = [r["uid"] for r in rows if r.get("uid")]

                ok_cnt = 0
                fail_cnt = 0
                failed_samples = []

                for uid in targets:
                    prof = get_profile(uid)
                    if prof:
                        upsert_basic_information_profile(conn, uid, prof)
                        ok_cnt += 1
                    else:
                        fail_cnt += 1
                        if len(failed_samples) < 10:
                            failed_samples.append(uid)

                    if sleep_ms:
                        time.sleep(sleep_ms / 1000.0)

                conn.commit()

                batches += 1
                total_ok += ok_cnt
                total_fail += fail_cnt
                last_failed_samples = failed_samples

                total = len(targets)
                batch_fail_rate = (fail_cnt / total) if total else 0.0

                # 失敗率高就加 sleep（避免被 LINE 限流）
                if batch_fail_rate >= fail_rate_threshold:
                    sleep_ms = min(500, int(sleep_ms * 1.5) or 1)

            finally:
                conn.close()

        elapsed = round(time.time() - started_at, 2)
        total = total_ok + total_fail
        fail_rate = (total_fail / total) if total else 0.0

        return {
            "ok": True,
            "stopped_reason": "done_or_reached_limit",
            "batches": batches,
            "elapsed_sec": elapsed,
            "total_ok": total_ok,
            "total_fail": total_fail,
            "total_fail_rate": round(fail_rate, 4),
            "final_sleep_ms": sleep_ms,
            "last_failed_samples": last_failed_samples,
        }

    finally:
        _RUN_LOCK.release()

@router.get("/audiences/status")
def audiences_status(
    staff: dict = Depends(get_current_staff),
):
    """
    回傳目前 basic_information 的補齊狀況：
    - total_with_uid / ready_profile_count / missing_xxx
    - remaining_missing
    - suggested batch/sleep
    """
    require_admin_staff(staff)

    conn = get_conn()
    try:
        meta = _detect_basic_information_columns(conn)
        uid_col = meta["uid"]
        display_col = meta["display"]
        picture_col = meta["picture"]
        created_col = meta["created"]
        updated_col = meta["updated"]

        if not uid_col:
            return {
                "ok": False,
                "error": "basic_information 沒有找到可用的 UID 欄位（例如 user_id / line_user_id）",
                "detected_columns": meta["all"],
            }

        uid_where = f"`{uid_col}` IS NOT NULL AND `{uid_col}` <> ''"

        has_display = bool(display_col)
        has_picture = bool(picture_col)

        def missing_expr(col: str) -> str:
            return f"(`{col}` IS NULL OR `{col}` = '')"

        with conn.cursor() as cur:
            # total
            cur.execute(f"SELECT COUNT(*) AS n FROM basic_information WHERE {uid_where}")
            total = int(cur.fetchone()["n"])

            missing_name = 0
            missing_pic = 0
            missing_any = 0

            # missing name
            if has_display:
                cur.execute(
                    f"SELECT COUNT(*) AS n FROM basic_information WHERE {uid_where} AND {missing_expr(display_col)}"
                )
                missing_name = int(cur.fetchone()["n"])

            # missing picture
            if has_picture:
                cur.execute(
                    f"SELECT COUNT(*) AS n FROM basic_information WHERE {uid_where} AND {missing_expr(picture_col)}"
                )
                missing_pic = int(cur.fetchone()["n"])

            # missing any
            if has_display and has_picture:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS n
                    FROM basic_information
                    WHERE {uid_where}
                      AND ({missing_expr(display_col)} OR {missing_expr(picture_col)})
                    """
                )
                missing_any = int(cur.fetchone()["n"])
            elif has_display:
                missing_any = missing_name
            elif has_picture:
                missing_any = missing_pic
            else:
                missing_any = 0

            # last updated / created
            last_updated_at = None
            last_created_at = None
            if updated_col or created_col:
                sel_parts = []
                if updated_col:
                    sel_parts.append(f"MAX(`{updated_col}`) AS last_updated_at")
                if created_col:
                    sel_parts.append(f"MAX(`{created_col}`) AS last_created_at")
                cur.execute(f"SELECT {', '.join(sel_parts)} FROM basic_information WHERE {uid_where}")
                r = cur.fetchone() or {}
                last_updated_at = r.get("last_updated_at")
                last_created_at = r.get("last_created_at")

            # updated today
            updated_today = None
            if updated_col:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS n
                    FROM basic_information
                    WHERE {uid_where}
                      AND `{updated_col}` >= CURDATE()
                    """
                )
                updated_today = int(cur.fetchone()["n"])

        # ---- 這邊開始是你要的新欄位（remaining + suggested） ----
        missing_rate = (missing_any / total) if total else 0.0
        ready = total - missing_any

        remaining_missing = missing_any

        # 建議 batch：最多 300（跟你的 /profiles limit 上限一致），剩下少就跑剩下的
        suggested_batch = 300 if remaining_missing >= 300 else remaining_missing

        # 建議 sleep：預設 80；如果今天更新很少，保守一點拉高（避免被 LINE rate limit）
        suggested_sleep_ms = 80
        if updated_today is not None and updated_today < 20:
            suggested_sleep_ms = 150

        return {
            "ok": True,
            "detected": {
                "uid_col": uid_col,
                "display_col": display_col,
                "picture_col": picture_col,
                "created_col": created_col,
                "updated_col": updated_col,
            },
            "total_with_uid": total,
            "ready_profile_count": ready,
            "missing": {
                "missing_name": missing_name if has_display else None,
                "missing_picture": missing_pic if has_picture else None,
                "missing_any": missing_any,
                "missing_rate": round(missing_rate, 4),
            },

            # ✅ 新增：還剩多少
            "remaining": {
                "remaining_missing": remaining_missing,
            },

            # ✅ 新增：建議下一次跑多少 + sleep
            "suggested": {
                "batch": suggested_batch,
                "sleep_ms": suggested_sleep_ms,
            },

            "activity": {
                "updated_today": updated_today,
                "last_updated_at": str(last_updated_at) if last_updated_at else None,
                "last_created_at": str(last_created_at) if last_created_at else None,
            },
        }
    finally:
        conn.close()

@router.post("/audiences/profiles/retry_failed")
def audiences_profiles_retry_failed(
    body: RetryBody,
    staff: dict = Depends(get_current_staff),
    sleep_ms: int = Query(default=120, ge=0, le=500),
):
    require_admin_staff(staff)

    conn = get_conn()
    try:
        ok_cnt = 0
        fail_cnt = 0
        failed = []

        for uid in body.user_ids[:300]:
            prof, err_code, err_msg = get_profile(uid)
            if prof:
                upsert_basic_information_profile(conn, uid, prof)
                ok_cnt += 1
            else:
                fail_cnt += 1
                mark_profile_failure(conn, uid, err_code or "unknown", err_msg or "")
                failed.append({"user_id": uid, "code": err_code, "msg": err_msg})

            if sleep_ms:
                time.sleep(sleep_ms / 1000.0)

        conn.commit()
        return {"ok": True, "ok_count": ok_cnt, "fail_count": fail_cnt, "failed": failed[:10]}
    finally:
        conn.close()

@router.get("/audiences/profiles/run_state")
def audiences_profiles_run_state(
    staff: dict = Depends(get_current_staff),
):
    require_admin_staff(staff)

    # 只回一份快照，避免你查的時候被改到一半
    s = dict(_RUN_STATE)
    s["last_batch"] = dict(_RUN_STATE.get("last_batch") or {})
    return {"ok": True, "state": s}

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
    一鍵跑到剩 0（或達到上限就停止）
    - admin-only
    - 單例鎖（同時只允許一個跑）
    - 有 max_batches / max_seconds 保護
    - 會寫入 /run_state 讓你查進度
    """
    require_admin_staff(staff)

    if not _RUN_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="audiences run is already in progress")

    started_at = time.time()

    # 初始化狀態
    _RUN_STATE.update({
        "running": True,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ended_at": None,
        "elapsed_sec": 0.0,
        "batches_done": 0,
        "max_batches": max_batches,
        "max_seconds": max_seconds,
        "batch_size": batch_size,
        "sleep_ms": sleep_ms,
        "total_ok": 0,
        "total_fail": 0,
        "message": "running",
        "last_batch": {
            "targets": 0,
            "ok": 0,
            "fail": 0,
            "fail_rate": 0.0,
            "failed_samples": [],
            "remaining_before": None,
            "remaining_after": None,
            "finished_at": None,
        },
    })

    try:
        while True:
            elapsed = time.time() - started_at
            _RUN_STATE["elapsed_sec"] = round(elapsed, 2)

            if elapsed > max_seconds:
                _RUN_STATE["message"] = "stopped: max_seconds reached"
                break
            if _RUN_STATE["batches_done"] >= max_batches:
                _RUN_STATE["message"] = "stopped: max_batches reached"
                break

            conn = get_conn()
            try:
                meta = _detect_basic_information_columns(conn)
                uid_col = meta["uid"]
                display_col = meta["display"]
                updated_col = meta["updated"]

                if not uid_col or not display_col:
                    _RUN_STATE["message"] = "error: basic_information uid/name column not found"
                    raise HTTPException(status_code=500, detail=_RUN_STATE["message"])

                uid_where = f"`{uid_col}` IS NOT NULL AND `{uid_col}` <> ''"
                missing_name_where = f"(`{display_col}` IS NULL OR `{display_col}`='')"
                order_by = f"`{updated_col}` ASC" if updated_col else f"`{uid_col}` ASC"

                with conn.cursor() as cur:
                    # remaining before
                    cur.execute(
                        f"SELECT COUNT(*) AS n FROM basic_information WHERE {uid_where} AND {missing_name_where}"
                    )
                    remaining_before = int(cur.fetchone()["n"])

                    if remaining_before <= 0:
                        _RUN_STATE["message"] = "done: remaining is 0"
                        break

                    # 抓這一批 targets（可搭配你之前的 fail_count/profile_status 排除條件）
                    cur.execute(
                        f"""
                        SELECT `{uid_col}` AS uid
                        FROM basic_information
                        WHERE {uid_where}
                          AND {missing_name_where}
                          AND (profile_fail_count < 3 OR profile_fail_count IS NULL)
                          AND (profile_status IS NULL OR profile_status <> 'unreachable')
                        ORDER BY {order_by}
                        LIMIT %s
                        """,
                        (batch_size,),
                    )
                    rows = cur.fetchall()

                targets = [r["uid"] for r in rows if r.get("uid")]

                ok_cnt = 0
                fail_cnt = 0
                failed_samples = []

                for uid in targets:
                    prof, err_code, err_msg = get_profile(uid)

                    if prof:
                        upsert_basic_information_profile(conn, uid, prof)
                        ok_cnt += 1
                    else:
                        fail_cnt += 1
                        mark_profile_failure(conn, uid, err_code or "unknown", err_msg or "")
                        if len(failed_samples) < 10:
                            failed_samples.append(uid)

                        # rate limit 稍微多睡一下
                        if err_code == "rate_limited":
                            time.sleep(0.3)

                    if sleep_ms:
                        time.sleep(sleep_ms / 1000.0)

                conn.commit()

                # remaining after（同一個 conn 再查一次）
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT COUNT(*) AS n FROM basic_information WHERE {uid_where} AND {missing_name_where}"
                    )
                    remaining_after = int(cur.fetchone()["n"])

                batch_total = len(targets)
                batch_fail_rate = (fail_cnt / batch_total) if batch_total else 0.0

                # 更新全域狀態
                _RUN_STATE["batches_done"] += 1
                _RUN_STATE["total_ok"] += ok_cnt
                _RUN_STATE["total_fail"] += fail_cnt
                _RUN_STATE["sleep_ms"] = sleep_ms  # 可能被動態調整

                _RUN_STATE["last_batch"] = {
                    "targets": batch_total,
                    "ok": ok_cnt,
                    "fail": fail_cnt,
                    "fail_rate": round(batch_fail_rate, 4),
                    "failed_samples": failed_samples,
                    "remaining_before": remaining_before,
                    "remaining_after": remaining_after,
                    "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

                # 失敗率高 → 自動加 sleep（保守）
                if batch_fail_rate >= fail_rate_threshold:
                    sleep_ms = min(500, max(1, int(sleep_ms * 1.5)))
                    _RUN_STATE["message"] = f"running (fail_rate high, increase sleep to {sleep_ms}ms)"
                else:
                    _RUN_STATE["message"] = "running"

            finally:
                conn.close()

        # 結束整理
        _RUN_STATE["running"] = False
        _RUN_STATE["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _RUN_STATE["elapsed_sec"] = round(time.time() - started_at, 2)

        total = _RUN_STATE["total_ok"] + _RUN_STATE["total_fail"]
        total_fail_rate = (_RUN_STATE["total_fail"] / total) if total else 0.0

        return {
            "ok": True,
            "message": _RUN_STATE["message"],
            "batches": _RUN_STATE["batches_done"],
            "elapsed_sec": _RUN_STATE["elapsed_sec"],
            "total_ok": _RUN_STATE["total_ok"],
            "total_fail": _RUN_STATE["total_fail"],
            "total_fail_rate": round(total_fail_rate, 4),
            "final_sleep_ms": _RUN_STATE["sleep_ms"],
            "last_batch": _RUN_STATE["last_batch"],
        }

    finally:
        _RUN_STATE["running"] = False
        _RUN_STATE["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _RUN_STATE["elapsed_sec"] = round(time.time() - started_at, 2)
        _RUN_LOCK.release()


