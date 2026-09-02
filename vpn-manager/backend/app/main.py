import os
import sys
import socket
import subprocess
import shutil
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
from .models import User, Router, VpnSessions
from .config import VPN_PUBLIC_IP, VPN_SSTP_PORT, VPN_L2TP_PORT

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
    version="1.2.0",
)


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path.lower()
    if path.endswith((".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff2", ".woff", ".ttf")):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
    elif path.endswith(".html") or path in ("/", "/login", "/dashboard", "/config"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
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


app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(profiles_router, prefix="/api/profiles", tags=["profiles"])
app.include_router(routers_api_router, prefix="/api", tags=["routers"])
app.include_router(monitoring_router, prefix="/api/monitoring", tags=["monitoring"])
app.include_router(configs_router, prefix="/api/configs", tags=["configs"])
app.include_router(vpn_router, prefix="/api/vpn", tags=["vpn"])


def _tcp_probe(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _run(cmd: list, timeout: int = 3) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return -1, "", str(e)


def _deep_health() -> dict:
    info = {}
    try:
        db = SessionLocal()
        try:
            users = db.query(User).count()
            routers = db.query(Router).count()
            sessions = db.query(VpnSessions).filter(VpnSessions.status == "active").count()
            info["db_ok"] = True
            info["users_count"] = users
            info["routers_count"] = routers
            info["active_sessions_db_count"] = sessions
        finally:
            db.close()
    except Exception as e:
        info["db_ok"] = False
        info["db_error"] = str(e)[:200]

    info["accel_ctrl_2001_ok"] = (
        shutil.which("accel-cmd") is not None and _tcp_probe("127.0.0.1", 2001, timeout=1.0)
    )

    info["xl2tpd_ctrl_ok"] = os.path.exists("/var/run/xl2tpd/l2tp-control") or _tcp_probe(
        "127.0.0.1", 1701, timeout=1.0
    ) or shutil.which("xl2tpd-control") is not None

    info["snat_vpn_public_ok"] = False
    if VPN_PUBLIC_IP and shutil.which("iptables"):
        try:
            rc, out, _err = _run(
                ["iptables", "-t", "nat", "-S", "POSTROUTING"],
                timeout=4,
            )
            snat_markers = [
                f"--to-source {VPN_PUBLIC_IP}",
                f"--to-source {VPN_PUBLIC_IP}/32",
            ]
            info["snat_vpn_public_ok"] = (
                rc == 0 and any(m in (out or "") for m in snat_markers)
            )
            info["snat_rule_sample"] = (
                next((l for l in (out or "").splitlines() if "POSTROUTING" in l or "SNAT" in l or "MASQUERADE" in l), None)
            )[:200] if info["snat_vpn_public_ok"] or out else None
        except Exception:
            pass

    chap_path = "/etc/ppp/chap-secrets"
    if os.path.exists(chap_path):
        try:
            sz = os.path.getsize(chap_path)
            with open(chap_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln for ln in f.readlines() if ln.strip() and not ln.strip().startswith("#")]
            info["chap_secrets_ok"] = True
            info["chap_secrets_size"] = sz
            info["chap_secrets_entries"] = len(lines)
        except Exception as e:
            info["chap_secrets_ok"] = False
            info["chap_secrets_error"] = str(e)[:200]
    else:
        info["chap_secrets_ok"] = None

    info["services"] = {}
    for svc in ("vpn-manager", "accel-ppp", "xl2tpd"):
        if shutil.which("systemctl"):
            rc, _o, _e = _run(["systemctl", "is-active", svc], timeout=3)
            info["services"][svc] = "active" if rc == 0 else "inactive"
        else:
            info["services"][svc] = "unknown"

    info["ports"] = {
        f"sstp_{VPN_SSTP_PORT}": _tcp_probe("0.0.0.0" if False else "127.0.0.1", int(VPN_SSTP_PORT or 443), timeout=1.0),
        f"mgmt_8000": True,
        f"l2tp_{VPN_L2TP_PORT}": _tcp_probe("127.0.0.1", int(VPN_L2TP_PORT or 1701), timeout=1.0),
    }
    return info


@app.get("/api/health")
async def health_check():
    base = {
        "status": "ok",
        "service": "vpn-vds-manager",
        "frontend_dir": str(FRONTEND_DIR) if FRONTEND_DIR else None,
    }
    try:
        deep = _deep_health()
    except Exception as e:
        deep = {"error": str(e)[:200]}
    base["checks"] = deep
    all_green = (
        deep.get("db_ok") is not False
        and deep.get("chap_secrets_ok") is not False
    )
    base["status"] = "ok" if all_green else "degraded"
    return base


@app.get("/api/info")
async def api_info():
    return {
        "name": "VPN VDS Manager API",
        "version": "1.2.0",
        "auth_required": True,
        "docs": "/docs",
        "frontend_dir": str(FRONTEND_DIR) if FRONTEND_DIR else None,
        "vpn": {
            "public_ip": VPN_PUBLIC_IP,
            "l2tp_port": VPN_L2TP_PORT,
            "sstp_port": VPN_SSTP_PORT,
        },
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


def _resolve_frontend_dir() -> Path:
    candidates = []
    env_fe = os.environ.get("FRONTEND_DIR")
    if env_fe:
        candidates.append(Path(env_fe))
    here = Path(__file__).resolve().parent
    candidates.append(here.parent.parent / "frontend")
    candidates.append(Path("/opt/server-promvpn/vpn-manager/frontend"))
    candidates.append(Path("/srv/vpn-manager/frontend"))
    candidates.append(Path.cwd() / "frontend")
    candidates.append(Path.cwd() / "vpn-manager" / "frontend")
    for c in candidates:
        try:
            if c.exists() and c.is_dir():
                idx = c / "index.html"
                log = c / "login.html"
                dash = c / "dashboard.html"
                if idx.exists() and log.exists() and dash.exists():
                    return c
        except Exception:
            continue
    return candidates[0] if candidates else Path("./frontend")


FRONTEND_DIR: Path | None = None
try:
    FRONTEND_DIR = _resolve_frontend_dir()
    print(f"[+] Frontend dir resolved: {FRONTEND_DIR}")
except Exception as e:
    print(f"[!] Frontend dir resolve failed: {e}")
    FRONTEND_DIR = None


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
