import os
import secrets
import sys
import warnings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_weak_secret_default = "your-super-secret-key-change-in-production"
_env_secret = os.getenv("SECRET_KEY", "").strip()
if _env_secret:
    SECRET_KEY = _env_secret
else:
    SECRET_KEY = secrets.token_urlsafe(48)
    warnings.warn(
        "SECRET_KEY env var is NOT set. Generated a RUNTIME-ONLY random secret. "
        "ALL existing JWT tokens will be INVALIDATED on next process restart. "
        f"Set SECRET_KEY=... in env for persistent sessions. Current: <{SECRET_KEY[:12]}...>"
    )

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

DB_URL = os.getenv("DB_URL", f"sqlite:///{BASE_DIR / 'vpn_manager.db'}")

_mgmt_ip = os.getenv("MGMT_IP", "").strip()
_vpn_public_ip = os.getenv("VPN_PUBLIC_IP", "").strip()
if _vpn_public_ip:
    VPN_SERVER = _vpn_public_ip
elif _mgmt_ip:
    VPN_SERVER = _mgmt_ip
else:
    VPN_SERVER = os.getenv("VPN_SERVER", "157.22.205.210")
VPN_L2TP_PORT = int(os.getenv("VPN_L2TP_PORT", "1701"))
VPN_SSTP_PORT = int(os.getenv("VPN_SSTP_PORT", "443"))
