# app/main.py  ── idiving5d-OctoFlow v260310
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db_pool, close_db_pool
from app.routes_callback   import router as callback_router
from app.routes_admin      import router as admin_router
from app.routes_ui         import router as ui_router
from app.routes_audiences  import router as audiences_router
from app.routes_groups     import router as groups_router
from app.routes_sessions   import router as sessions_router
from app.routes_notify     import router as notify_router
from app.routes_quickreply import router as quickreply_router
from app.routes_crawler    import router as crawler_router
from app.routes_payment    import router as payment_router
from app.routes_liff       import router as liff_router
from app.routes_tags       import router as tags_router
from app.routes_courses    import public_router as courses_public_router
from app.routes_courses    import admin_router  as courses_admin_router
from app.routes_pageviews  import public_router as pageviews_public_router
from app.routes_pageviews  import admin_router  as pageviews_admin_router
from app.routes_linestats    import router        as linestats_router
from app.routes_registration import public_router as reg_public_router
from app.routes_registration import admin_router  as reg_admin_router
from app.daily_report        import daily_report_scheduler


# 應用程式生命週期管理：啟動時建立 DB 連線池，關閉時釋放
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 啟動：建立 DB 連線池 ──────────────────────────────
    await init_db_pool()
    asyncio.create_task(daily_report_scheduler())
    yield
    # ── 關閉：釋放連線池 ──────────────────────────────────
    await close_db_pool()


app = FastAPI(
    title="idiving5d-OctoFlow",
    version="260310",
    lifespan=lifespan,
)

# /api/* 為官網公開端點（analytics、課程資訊），允許所有來源跨域
# admin/* 走 X-Admin-Token 驗證，瀏覽器不會直接呼叫，不需要限制 origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Token"],
)

app.include_router(callback_router)
app.include_router(admin_router,      prefix="/admin/api")
app.include_router(ui_router)
app.include_router(audiences_router,  prefix="/admin/api")
app.include_router(groups_router,     prefix="/admin/api")
app.include_router(sessions_router,   prefix="/admin/api")
app.include_router(notify_router,     prefix="/internal")
app.include_router(quickreply_router, prefix="/admin/api")
app.include_router(crawler_router,    prefix="/internal")
app.include_router(payment_router,    prefix="/admin/api")
app.include_router(liff_router,       prefix="/liff")
app.include_router(tags_router,           prefix="/admin/api")
app.include_router(courses_public_router,   prefix="/api")
app.include_router(courses_admin_router,    prefix="/admin/api")
app.include_router(pageviews_public_router, prefix="/api")
app.include_router(pageviews_admin_router,  prefix="/admin/api")
app.include_router(linestats_router,        prefix="/admin/api")
app.include_router(reg_public_router,       prefix="/api")
app.include_router(reg_admin_router,        prefix="/admin/api")


# 根路由：確認服務是否正常運行
@app.get("/")
def index():
    return "OK - idiving5d-OctoFlow is running"


# 健康檢查端點：回傳服務狀態與版本號
@app.get("/health")
def health():
    return {"ok": True, "version": "idiving5d-OctoFlow v260310"}
