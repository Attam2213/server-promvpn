import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, engine, SessionLocal
from .auth import get_password_hash
from .models import User

from .routers.auth import router as auth_router
from .routers.profiles import router as profiles_router
from .routers.routers_api import router as routers_api_router
from .routers.monitoring import router as monitoring_router
from .routers.configs import router as configs_router
from .routers.vpn import router as vpn_router

Base.metadata.create_all(bind=engine)

def _create_default_admin():
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        if user_count == 0:
            admin = User(
                username="admin",
                hashed_password=get_password_hash("admin"),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
            print("[+] Default admin created: admin / admin")
    finally:
        db.close()

_create_default_admin()

app = FastAPI(
    title="VPN VDS Manager API",
    description="Менеджер VPN и конфигураций MikroTik (L2TP + SSTP)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(routers_api_router)
app.include_router(monitoring_router)
app.include_router(configs_router)
app.include_router(vpn_router, prefix="/api/vpn", tags=["VPN Management"])

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "vpn-vds-manager"}


@app.get("/api/info")
async def api_info():
    return {
        "name": "VPN VDS Manager API",
        "version": "1.0.0",
        "default_login": "admin / admin (CHANGE THIS!)",
        "docs": "/docs",
        "endpoints": {
            "auth": [
                "POST /api/auth/login (OAuth2 form)",
                "GET /api/auth/me",
            ],
            "profiles": [
                "GET /api/profiles",
                "POST /api/profiles",
                "GET /api/profiles/{id}",
                "PUT /api/profiles/{id}",
                "DELETE /api/profiles/{id}",
            ],
            "routers": [
                "GET /api/profiles/{pid}/routers",
                "POST /api/profiles/{pid}/routers",
                "PUT /api/profiles/{pid}/routers/{id}",
                "DELETE /api/profiles/{pid}/routers/{id}",
            ],
            "monitoring": [
                "GET /api/monitoring/sessions",
                "GET /api/monitoring/router/{router_id}",
                "GET /api/monitoring/stats",
            ],
            "configs": [
                "GET /api/configs/schema",
                "POST /api/configs/validate",
                "POST /api/configs/build",
            ],
            "vpn": [
                "GET /api/vpn/users",
                "POST /api/vpn/users",
                "DELETE /api/vpn/users/{username}",
                "POST /api/vpn/sync",
                "POST /api/vpn/restart",
            ],
        },
    }


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_root():
        return FileResponse(str(FRONTEND_DIR / "login.html"))

    @app.get("/login", include_in_schema=False)
    async def serve_login_alias():
        return FileResponse(str(FRONTEND_DIR / "login.html"))

    @app.get("/dashboard", include_in_schema=False)
    async def serve_dashboard():
        return FileResponse(str(FRONTEND_DIR / "dashboard.html"))

    @app.get("/config", include_in_schema=False)
    async def serve_config():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("docs") or full_path.startswith("openapi") or full_path.startswith("redoc"):
            return
        requested = FRONTEND_DIR / full_path
        if requested.exists() and requested.is_file():
            return FileResponse(str(requested))
        return FileResponse(str(FRONTEND_DIR / "login.html"))
