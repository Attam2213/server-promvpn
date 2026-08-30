import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

DB_URL = os.getenv("DB_URL", f"sqlite:///{BASE_DIR / 'vpn_manager.db'}")

VPN_SERVER = os.getenv("VPN_SERVER", "185.253.182.24")
VPN_L2TP_PORT = int(os.getenv("VPN_L2TP_PORT", "1701"))
VPN_SSTP_PORT = int(os.getenv("VPN_SSTP_PORT", "943"))
