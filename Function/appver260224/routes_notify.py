import os
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_TO_ID = "Ua79fedbceaee4227c31a684d06e2aeef"          # userId 或 groupId 或 roomId
NOTIFY_TOKEN = "RsSkNneLP0opeVEoX_nL7fqsFXi42PlMuk3dXcfmtEs"     # 跟 checker.py 一樣
# ── ENV ──────────────────────────────────────────────────────
#LINE_CHANNEL_SECRET       = os.environ.get("LINE_CHANNEL_SECRET", "")
#LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

class NotifyIn(BaseModel):
    token: str
    url: str
    hash: str
    preview: str

def line_push(text: str):
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "to": LINE_TO_ID,
        "messages": [{"type": "text", "text": text}],
    }
    r = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=data, timeout=15)
    r.raise_for_status()

@router.post("/notify")
def internal_notify(body: NotifyIn):
    if body.token != NOTIFY_TOKEN:
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