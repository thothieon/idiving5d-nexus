# idiving5d-OctoFlow v260310

> iDiving LINE@ 智能客服系統 ── FastAPI + aiomysql + Docker

---

## 專案概述

**idiving5d-OctoFlow** 是 iDiving 潛水中心的 LINE@ 客服後台系統，採用 FastAPI 非同步架構，整合 LINE Messaging API、MySQL 連線池、Quick Reply 關鍵字自動回覆、課程爬蟲快照，以及完整的工單狀態機。

| 版本 | 日期 | 說明 |
|------|------|------|
| v260306 | 2026-03-06 | aiomysql 全面 async 重構、Quick Reply 系統上線 |
| **v260310** | **2026-03-10** | 專案更名 idiving5d-OctoFlow、Python 升 3.12、Dockerfile 清理、notify 改讀環境變數、bootstrap 修正亂碼 |

---

## 技術棧

| 層級 | 技術 |
|------|------|
| Web 框架 | FastAPI 0.115 + Uvicorn |
| 程序管理 | Gunicorn + UvicornWorker |
| 資料庫 | MySQL 8 + aiomysql 0.2 (async 連線池) |
| LINE SDK | line-bot-sdk 3.12 + httpx |
| 容器 | Docker (Python 3.12-slim) + docker-compose |
| 反向代理 | Nginx (靜態網站) + Cloudflare Tunnel |

---

## 目錄結構

```
idiving5d-OctoFlow-v260310/
├── app/
│   ├── main.py                  # FastAPI 入口、lifespan、router 注冊
│   ├── db.py                    # aiomysql 連線池 (init/close/get_conn)
│   ├── auth_staff.py            # X-Admin-Token 驗證
│   ├── security_staff_tokens.py # Token 產生與 SHA-256 雜湊
│   ├── session_manager.py       # 工單狀態機核心
│   ├── quick_reply_handler.py   # Quick Reply 規則 + 60s cache
│   ├── routes_callback.py       # LINE Webhook 接收
│   ├── routes_admin.py          # 客服後台 API (訊息/工單/備註)
│   ├── routes_sessions.py       # 工單狀態轉換 API
│   ├── routes_quickreply.py     # Quick Reply 規則 CRUD
│   ├── routes_groups.py         # LINE 群組/身份資料 API
│   ├── routes_audiences.py      # 受眾分群 API
│   ├── routes_notify.py         # 課程更新內部推播
│   ├── routes_crawler.py        # 爬蟲快照儲存 API
│   └── routes_ui.py             # 管理後台 UI 頁面路由
├── bootstrap_admin_token.py     # 一次性建立 admin token 工具
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## 快速啟動

### 1. 設定環境變數

複製 `docker-compose.yml` 並填入實際值：

```yaml
LINE_CHANNEL_SECRET:       "your_secret"
LINE_CHANNEL_ACCESS_TOKEN: "your_token"
LINE_NOTIFY_TO_ID:         "Uxxxxxxxx"   # 接收通知的 userId/groupId
NOTIFY_TOKEN:              "your_notify_token"
CRAWLER_SECRET:            "your_crawler_secret"
DB_HOST:                   "192.168.x.x"
DB_PASSWORD:               "your_db_password"
```

### 2. 啟動容器

```bash
docker compose up -d --build
```

### 3. 建立第一個 Admin Token

```bash
# 先確保 staff 表已有 id=1 的管理員
python bootstrap_admin_token.py --staff-id 1 --label "admin-init"
# 輸出的 RAW_TOKEN 即為 X-Admin-Token header 值
```

### 4. 驗證服務

```bash
curl http://localhost:5000/health
# {"ok": true, "version": "idiving5d-OctoFlow v260310"}
```

---

## API 路由總覽

### LINE Webhook
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/callback` | LINE Webhook 入口 |
| POST | `/idiving_callback_test` | 測試用 echo |

### 客服後台 `/admin/api/`
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/tickets/active` | 取得進行中工單列表 |
| GET | `/tickets/{id}/status` | 工單狀態 |
| POST | `/tickets/{id}/transition` | 狀態機轉換 |
| POST | `/tickets/{id}/reply` | 客服回覆訊息 |
| GET/POST | `/tickets/{id}/booking` | 報名資料 |
| POST | `/tickets/{id}/booking/confirm` | 確認/取消報名 |
| GET/POST/PUT/DELETE | `/quickreply/rules` | Quick Reply 規則管理 |
| GET | `/customers/sync_profiles` | 同步 LINE 大頭貼 |
| GET | `/dashboard` | 儀表板統計 |

### 內部服務 `/internal/`
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/notify` | 課程更新推播通知 |
| POST | `/crawler/snapshot` | 儲存課程快照 |
| GET | `/crawler/last_hash` | 查詢課程最新 hash |

---

## 工單狀態機

```
new ──→ waiting ──→ in_progress ──→ collecting ──┐
 ↑                      ↑                        ↓
 └──────── closed ←─────┴──────── booking ←──────┘
```

| 狀態 | 說明 |
|------|------|
| `new` | 新訊息，尚未客服接手 |
| `waiting` | 客戶等待回覆中 |
| `in_progress` | 客服服務中 |
| `collecting` | 資料收集中 |
| `booking` | 報名/預約填寫中 |
| `closed` | 結案 |

---

## Quick Reply 機制

1. LINE 訊息進入 `/callback`
2. 比對 `quick_reply_rules` 表中的關鍵字（完全符合）
3. 命中時自動推送 Quick Reply 按鈕訊息（最多 13 個 URI 按鈕）
4. 規則帶 60 秒 in-memory cache，後台更新後自動失效

---

## 主要改動紀錄 (v260306 → v260310)

- **Dockerfile**：基礎映像升為 `python:3.12-slim`，移除殘留 Flask 環境變數及 sqlite3 套件
- **routes_notify.py**：`LINE_NOTIFY_TO_ID` 與 `NOTIFY_TOKEN` 改讀環境變數，不再 hardcode
- **routes_crawler.py**：移除 SELECT 查詢後多餘的 `await conn.commit()`
- **bootstrap_admin_token.py**：修正 BIG5 亂碼，重寫為 async aiomysql 版本
- 全專案版本字串更新為 `idiving5d-OctoFlow v260310`

---

## 注意事項

- `docker-compose.yml` 內含敏感憑證，請勿提交到公開 Git repository
- LINE Token 定期輪換後需同步更新環境變數並重啟容器
- MySQL 連線池預設 minsize=3 / maxsize=20，可依負載調整 `db.py`
