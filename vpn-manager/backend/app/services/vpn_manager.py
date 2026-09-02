import json
import logging
import os
import shutil
import subprocess
from typing import Optional

from ..models import Router

logger = logging.getLogger(__name__)


CHAP_SECRETS_PATH = "/etc/ppp/chap-secrets"
ACCEL_PPP_SECRETS_PATH = "/etc/accel-ppp/conf/chap-secrets"
ACCEL_PPP_CONFIG_PATH = "/etc/accel-ppp/accel-ppp.conf"


class VpnManager:
    def __init__(self):
        self._use_fallback = False
        self._fallback_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "..",
            "vpn_users.json",
        )
        self._fallback_path = os.path.abspath(self._fallback_path)
        self._detect_storage_mode()
        self._sstp_available = self._detect_sstp()

    def _detect_sstp(self) -> bool:
        return (
            shutil.which("accel-pppd") is not None
            or os.path.exists(ACCEL_PPP_CONFIG_PATH)
        )

    def _detect_storage_mode(self):
        if os.name == "nt":
            self._use_fallback = True
            return
        if not os.path.exists(CHAP_SECRETS_PATH):
            try:
                chap_dir = os.path.dirname(CHAP_SECRETS_PATH)
                if os.path.isdir(chap_dir) and os.access(chap_dir, os.W_OK):
                    self._use_fallback = False
                    return
            except Exception as e:
                logger.exception("VpnManager._detect_storage_mode chap_dir access failed")
            self._use_fallback = True
            return
        if not os.access(CHAP_SECRETS_PATH, os.R_OK) or not os.access(CHAP_SECRETS_PATH, os.W_OK):
            self._use_fallback = True
            return
        self._use_fallback = False

    def _parse_chap_line(self, line: str) -> Optional[dict]:
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        parts = line.split()
        if len(parts) < 4:
            return None
        username, server, secret, ip_address = parts[0], parts[1], parts[2], parts[3]
        return {
            "username": username,
            "password": secret,
            "ip_address": ip_address,
        }

    def list_users(self) -> list[dict]:
        if self._use_fallback:
            return self._list_users_fallback()
        return self._list_users_chap()

    def _list_users_chap(self) -> list[dict]:
        users = []
        try:
            with open(CHAP_SECRETS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    user = self._parse_chap_line(line)
                    if user:
                        users.append(user)
        except Exception as e:
            logger.exception("VpnManager._list_users_chap failed")
            return []
        return users

    def _list_users_fallback(self) -> list[dict]:
        if not os.path.exists(self._fallback_path):
            return []
        try:
            with open(self._fallback_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                return []
        except (json.JSONDecodeError, Exception) as e:
            logger.exception("VpnManager._list_users_fallback failed")
            return []

    def add_user(self, username: str, password: str, ip_address: str = "*") -> bool:
        if not username or not password:
            return False
        added_chap = False
        if self._use_fallback:
            added_chap = self._add_user_fallback(username, password, ip_address)
        else:
            added_chap = self._add_user_chap(username, password, ip_address)
        self._add_user_sstp(username, password, ip_address)
        return added_chap

    def _add_user_chap(self, username: str, password: str, ip_address: str) -> bool:
        try:
            existing = self._list_users_chap()
            for user in existing:
                if user["username"] == username:
                    return False
            with open(CHAP_SECRETS_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n{username}\t*\t{password}\t{ip_address}\n")
            return True
        except Exception as e:
            logger.exception("VpnManager._add_user_chap failed for user=%s", username)
            return False

    def _add_user_sstp(self, username: str, password: str, ip_address: str) -> bool:
        if not self._sstp_available:
            return False
        try:
            secrets_dir = os.path.dirname(ACCEL_PPP_SECRETS_PATH)
            if not os.path.exists(secrets_dir):
                os.makedirs(secrets_dir, exist_ok=True)
            existing = set()
            if os.path.exists(ACCEL_PPP_SECRETS_PATH):
                with open(ACCEL_PPP_SECRETS_PATH, "r", encoding="utf-8") as f:
                    for line in f:
                        u = self._parse_chap_line(line)
                        if u:
                            existing.add(u["username"])
            if username in existing:
                return False
            with open(ACCEL_PPP_SECRETS_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n{username}\t*\t{password}\t{ip_address}\n")
            return True
        except Exception as e:
            logger.exception("VpnManager._add_user_sstp failed for user=%s", username)
            return False

    def _add_user_fallback(self, username: str, password: str, ip_address: str) -> bool:
        try:
            users = self._list_users_fallback()
            for user in users:
                if user["username"] == username:
                    return False
            users.append({
                "username": username,
                "password": password,
                "ip_address": ip_address,
            })
            os.makedirs(os.path.dirname(self._fallback_path), exist_ok=True)
            with open(self._fallback_path, "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.exception("VpnManager._add_user_fallback failed for user=%s", username)
            return False

    def remove_user(self, username: str) -> bool:
        if not username:
            return False
        removed = False
        if self._use_fallback:
            removed = self._remove_user_fallback(username)
        else:
            removed = self._remove_user_chap(username)
        removed_sstp = self._remove_user_sstp(username)
        return removed or removed_sstp

    def _remove_user_chap(self, username: str) -> bool:
        try:
            if not os.path.exists(CHAP_SECRETS_PATH):
                return False
            with open(CHAP_SECRETS_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            found = False
            new_lines = []
            for line in lines:
                user = self._parse_chap_line(line)
                if user and user["username"] == username:
                    found = True
                    continue
                new_lines.append(line)
            if not found:
                return False
            with open(CHAP_SECRETS_PATH, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return True
        except Exception as e:
            logger.exception("VpnManager._remove_user_chap failed for user=%s", username)
            return False

    def _remove_user_sstp(self, username: str) -> bool:
        if not self._sstp_available or not os.path.exists(ACCEL_PPP_SECRETS_PATH):
            return False
        try:
            with open(ACCEL_PPP_SECRETS_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()
            found = False
            new_lines = []
            for line in lines:
                user = self._parse_chap_line(line)
                if user and user["username"] == username:
                    found = True
                    continue
                new_lines.append(line)
            if not found:
                return False
            with open(ACCEL_PPP_SECRETS_PATH, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return True
        except Exception as e:
            logger.exception("VpnManager._remove_user_sstp failed for user=%s", username)
            return False

    def _remove_user_fallback(self, username: str) -> bool:
        try:
            users = self._list_users_fallback()
            original_len = len(users)
            users = [u for u in users if u["username"] != username]
            if len(users) == original_len:
                return False
            os.makedirs(os.path.dirname(self._fallback_path), exist_ok=True)
            with open(self._fallback_path, "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.exception("VpnManager._remove_user_fallback failed for user=%s", username)
            return False

    def restart_services(self) -> bool:
        if self._use_fallback:
            return True
        services = ["xl2tpd", "accel-ppp", "ipsec", "strongswan"]
        restarted_any = False
        for svc in services:
            if not shutil.which("systemctl"):
                continue
            try:
                is_active = subprocess.run(
                    ["systemctl", "is-active", "--quiet", svc],
                    capture_output=True,
                )
                exists = subprocess.run(
                    ["systemctl", "list-unit-files", "--full", "--no-legend"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                is_exists = f"{svc}.service" in (exists.stdout or "")
                if is_active.returncode == 0 or is_exists:
                    res = subprocess.run(
                        ["systemctl", "restart", svc],
                        capture_output=True,
                        check=False,
                    )
                    if res.returncode == 0:
                        restarted_any = True
                    else:
                        logger.error(
                            "VpnManager.restart_services: systemctl restart %s failed rc=%s stderr=%s",
                            svc, res.returncode, (res.stderr or b"").decode(errors="replace")[:200]
                        )
            except Exception as e:
                logger.exception("VpnManager.restart_services exception on svc=%s", svc)
                continue
        return restarted_any

    def sync_routers_to_vpn(self, db_session) -> dict:
        result = {"added": 0, "removed": 0, "skipped": 0}
        routers = db_session.query(Router).all()
        db_users = {}
        for router in routers:
            values = router.values or {}
            l2tp_user = values.get("l2tpUser")
            l2tp_password = values.get("l2tpPassword")
            if l2tp_user and l2tp_password:
                ip_address = values.get("l2tpIpAddress", "*")
                db_users[l2tp_user] = {
                    "username": l2tp_user,
                    "password": l2tp_password,
                    "ip_address": ip_address,
                }
            sstp_user = values.get("sstpUser")
            sstp_password = values.get("sstpPassword")
            if sstp_user and sstp_password:
                ip_address = values.get("sstpIpAddress", "*")
                db_users[sstp_user] = {
                    "username": sstp_user,
                    "password": sstp_password,
                    "ip_address": ip_address,
                }
            default_user = values.get("pppoeUsername")
            default_pw = values.get("pppoePassword")
            if default_user and default_pw:
                ip_address = values.get("l2tpIpAddress", "*")
                db_users[default_user] = {
                    "username": default_user,
                    "password": default_pw,
                    "ip_address": ip_address,
                }
        existing_users = self.list_users()
        existing_usernames = {u["username"] for u in existing_users}
        for username, user_data in db_users.items():
            if username in existing_usernames:
                result["skipped"] += 1
            else:
                if self.add_user(
                    user_data["username"],
                    user_data["password"],
                    user_data["ip_address"],
                ):
                    result["added"] += 1
                else:
                    result["skipped"] += 1
        db_usernames = set(db_users.keys())
        for user in existing_users:
            if user["username"] not in db_usernames:
                if self.remove_user(user["username"]):
                    result["removed"] += 1
        return result
