# app/main.py
import os
from fastapi import FastAPI
from app.routes_callback  import router as callback_router
from app.routes_admin     import router as admin_router
from app.routes_ui        import router as ui_router
from app.routes_audiences import router as audiences_router
from app.routes_groups    import router as groups_router
from app.routes_sessions  import router as sessions_router
from app.routes_notify    import router as notify_router

app = FastAPI(title="iDiving Linebot", version="260306")

app.include_router(callback_router)
app.include_router(admin_router, prefix="/admin/api")
app.include_router(ui_router)
app.include_router(audiences_router, prefix="/admin/api")
app.include_router(groups_router, prefix="/admin/api")
app.include_router(sessions_router, prefix="/admin/api")
app.include_router(notify_router, prefix="/internal")

@app.get("/")
def index():
    return "OK - linebotapp is running"

@app.get("/health")
def health():
    return {"ok": True}
