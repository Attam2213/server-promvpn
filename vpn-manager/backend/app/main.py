import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

try:
    from fastapi.staticfiles import StaticFiles
    _STATIC_AVAILABLE = True
except Exception:
    _STATIC_AVAILABLE = False

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
            env_pw = os.environ.get("ADMIN_PASSWORD", "").strip()
            if not env_pw:
                print(
                    "[FATAL DB BOOTSTRAP] Users table is EMPTY and ADMIN_PASSWORD env "
                    "var is NOT set. Cannot create default admin account. Login will be "
                    "impossible. Set ADMIN_PASSWORD=... in systemd unit / environment "
                    "and restart vpn-manager.service. ABORTING bootstrap."
                )
                sys.stderr.write(
                    "[FATAL] empty users + no ADMIN_PASSWORD env — startup aborted\n"
                )
                return
            admin = User(
                username="admin",
                hashed_password=get_password_hash(env_pw),
                is_admin=True,
            )
            db.add(admin)
            db.commit()
            print("[+] Default admin created: admin / <from ADMIN_PASSWORD env>")
    except Exception as e:
        print(f"[!] Warning: failed to create default admin: {e}")
    finally:
        db.close()

_create_default_admin()

app = FastAPI(
    title="VPN VDS Manager API",
    description="Менеджер VPN и конфигураций MikroTik (L2TP + SSTP)",
    version="1.0.1",
)

@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if isinstance(response, Response):
        path = request.url.path.lower()
        query = request.url.query or ""
        has_cache_key = "v=" in query
        if path.endswith(".html") or (not any(path.endswith(ext) for ext in (".js",".css",".png",".jpg",".jpeg",".gif",".svg",".ico",".woff",".woff2",".ttf")) and path.startswith(("/login","/dashboard","/config","/"))):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.endswith((".js", ".css")):
            if has_cache_key:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(profiles_router)
app.include_router(routers_api_router)
app.include_router(monitoring_router)
app.include_router(configs_router)
app.include_router(vpn_router)

def _resolve_frontend_dir() -> Path:
    candidates = []
    env_frontend = os.environ.get("FRONTEND_DIR", "").strip()
    if env_frontend:
        candidates.append(Path(env_frontend))
    this_file = Path(__file__).resolve()
    candidates.append(this_file.parent.parent.parent / "frontend")
    candidates.append(this_file.parent.parent / "frontend")
    candidates.append(Path.cwd().resolve() / "frontend")
    candidates.append(Path("/opt/server-promvpn/vpn-manager/frontend"))
    candidates.append(Path("/opt/vpn-manager/frontend"))
    for p in candidates:
        try:
            if p and p.exists() and p.is_dir() and (p / "login.html").exists():
                return p
        except Exception:
            continue
    return None

FRONTEND_DIR = _resolve_frontend_dir()
if FRONTEND_DIR:
    print(f"[+] Frontend dir resolved: {FRONTEND_DIR}")
else:
    print("[!] Frontend dir not found — SPA routing disabled, API-only mode.")

@app.get("/api/health")
async def health_check():
    info = {
        "status": "ok",
        "service": "vpn-vds-manager",
        "frontend_dir": str(FRONTEND_DIR) if FRONTEND_DIR else None,
    }
    return info


@app.get("/api/info")
async def api_info():
    return {
        "name": "VPN VDS Manager API",
        "version": "1.1.0",
        "auth_required": True,
        "docs": "/docs",
        "frontend_dir": str(FRONTEND_DIR) if FRONTEND_DIR else None,
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


if FRONTEND_DIR and _STATIC_AVAILABLE:
    try:
        app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
    except Exception as e:
        print(f"[!] Failed to mount static frontend dir: {e}")

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
        reserved = ("api/", "docs", "openapi.json", "redoc")
        for r in reserved:
            if full_path == r or full_path.startswith(r):
                return JSONResponse(status_code=404, content={"detail": "not found"})
        requested = FRONTEND_DIR / full_path
        try:
            if requested.exists() and requested.is_file():
                return FileResponse(str(requested))
        except Exception:
            pass
        fallback = FRONTEND_DIR / "login.html"
        if fallback.exists():
            return FileResponse(str(fallback))
        return JSONResponse(status_code=404, content={"detail": "frontend file not found"})
