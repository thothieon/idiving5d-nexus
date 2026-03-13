# app/routes_notify.py  ── idiving5d-OctoFlow v260310
import os
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

LINE_TOKEN    = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_TO_ID    = os.environ.get("LINE_NOTIFY_TO_ID", "")   # userId / groupId / roomId
NOTIFY_TOKEN  = os.environ.get("NOTIFY_TOKEN", "")        # 和 checker.py 共用的驗證 token


class NotifyIn(BaseModel):
    token:   str
    url:     str
    hash:    str
    preview: str


def line_push(text: str):
    if not LINE_TO_ID:
        raise RuntimeError("LINE_NOTIFY_TO_ID 未設定")
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "to": LINE_TO_ID,
        "messages": [{"type": "text", "text": text}],
    }
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=headers,
        json=data,
        timeout=15,
    )
    r.raise_for_status()


@router.post("/notify")
def internal_notify(body: NotifyIn):
    if not NOTIFY_TOKEN or body.token != NOTIFY_TOKEN:
        raise HTTPException(status_code=403, detail="Bad token")

    msg = (
        "📌 SSI 教材疑似更新\n"
        f"URL: {body.url}\n"
        f"Hash: {body.hash}\n\n"
        "變更摘要（前幾行）：\n"
        + "\n".join(body.preview.splitlines()[:12])
    )
    line_push(msg)
    return {"ok": True}
