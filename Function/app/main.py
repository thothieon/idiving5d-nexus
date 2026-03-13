# app/main.py  ── idiving5d-OctoFlow v260310
from contextlib import asynccontextmanager
from fastapi import FastAPI

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── 啟動：建立 DB 連線池 ──────────────────────────────
    await init_db_pool()
    yield
    # ── 關閉：釋放連線池 ──────────────────────────────────
    await close_db_pool()


app = FastAPI(
    title="idiving5d-OctoFlow",
    version="260310",
    lifespan=lifespan,
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


@app.get("/")
def index():
    return "OK - idiving5d-OctoFlow is running"


@app.get("/health")
def health():
    return {"ok": True, "version": "idiving5d-OctoFlow v260310"}
