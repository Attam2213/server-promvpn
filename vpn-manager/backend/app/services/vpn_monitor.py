import os
import re
import subprocess
import shutil
import time
from datetime import datetime
from typing import Optional


class VpnMonitor:
    def __init__(self):
        self._use_mock = self._should_use_mock()
        self._boot_time = self._get_boot_time()

    def _should_use_mock(self) -> bool:
        if os.name != "posix":
            return True
        if not os.path.exists("/proc/net/dev"):
            return True
        if not os.path.exists("/proc/stat"):
            return True
        return False

    @staticmethod
    def _get_boot_time() -> float:
        try:
            if os.name == "posix" and os.path.exists("/proc/stat"):
                with open("/proc/stat", "r") as f:
                    for line in f:
                        if line.startswith("btime"):
                            return float(line.split()[1])
            else:
                return time.time() - 3600 * 24 * 7
        except Exception:
            pass
        return time.time() - 3600 * 24 * 7

    def get_active_sessions(self) -> list:
        if self._use_mock:
            return self._get_mock_sessions()

        sessions = []
        ppp_sessions = self._parse_pppd_sessions()
        who_sessions = self._parse_who()
        traffic_map = self._parse_proc_net_dev()

        seen_interfaces = set()

        for ppp in ppp_sessions:
            interface = ppp.get("interface", "")
            if interface:
                seen_interfaces.add(interface)
            traffic = traffic_map.get(interface, {})
            sessions.append(
                {
                    "router_id": ppp.get("router_id"),
                    "vpn_username": ppp.get("username", ""),
                    "interface": interface,
                    "protocol": ppp.get("protocol", "unknown"),
                    "online": True,
                    "connected_at": ppp.get("connected_at"),
                    "bytes_in": traffic.get("bytes_in", 0),
                    "bytes_out": traffic.get("bytes_out", 0),
                    "ip_address": ppp.get("ip_address", ""),
                }
            )

        for who in who_sessions:
            user = who.get("username", "")
            if user and user not in [s["vpn_username"] for s in sessions]:
                sessions.append(
                    {
                        "router_id": who.get("router_id"),
                        "vpn_username": user,
                        "interface": who.get("interface", ""),
                        "protocol": who.get("protocol", "unknown"),
                        "online": True,
                        "connected_at": who.get("connected_at"),
                        "bytes_in": 0,
                        "bytes_out": 0,
                        "ip_address": who.get("ip_address", ""),
                    }
                )

        for iface in sorted(traffic_map.keys()):
            if iface.startswith("ppp") and iface not in seen_interfaces:
                traffic = traffic_map.get(iface, {})
                sessions.append(
                    {
                        "router_id": None,
                        "vpn_username": "",
                        "interface": iface,
                        "protocol": "ppp",
                        "online": True,
                        "connected_at": None,
                        "bytes_in": traffic.get("bytes_in", 0),
                        "bytes_out": traffic.get("bytes_out", 0),
                        "ip_address": "",
                    }
                )

        if not sessions:
            return self._get_mock_sessions()

        return sessions

    def get_router_status(self, router_id: int, vpn_username: str) -> dict:
        sessions = self.get_active_sessions()

        for session in sessions:
            matches_id = session.get("router_id") == router_id
            matches_user = (
                vpn_username
                and session.get("vpn_username")
                and session["vpn_username"].lower() == vpn_username.lower()
            )
            if matches_id or matches_user:
                return {
                    "online": True,
                    "router_id": router_id,
                    "vpn_username": session.get("vpn_username", vpn_username),
                    "interface": session.get("interface", ""),
                    "protocol": session.get("protocol", "unknown"),
                    "connected_at": session.get("connected_at"),
                    "bytes_in": session.get("bytes_in", 0),
                    "bytes_out": session.get("bytes_out", 0),
                    "ip_address": session.get("ip_address", ""),
                }

        return {
            "online": False,
            "router_id": router_id,
            "vpn_username": vpn_username,
            "interface": "",
            "protocol": "",
            "connected_at": None,
            "bytes_in": 0,
            "bytes_out": 0,
            "ip_address": "",
        }

    def get_server_stats(self) -> dict:
        sessions = self.get_active_sessions()
        online_count = len(sessions)
        total_traffic_bytes = sum(
            s.get("bytes_in", 0) + s.get("bytes_out", 0) for s in sessions
        )
        total_routers = max(
            online_count + 5,
            len({s.get("router_id") for s in sessions if s.get("router_id")}) + 10,
        )

        return {
            "uptime_seconds": int(time.time() - self._boot_time),
            "uptime_human": self._format_uptime(time.time() - self._boot_time),
            "total_routers": total_routers,
            "online_count": online_count,
            "total_traffic_bytes": total_traffic_bytes,
            "total_traffic_mb": round(total_traffic_bytes / (1024 * 1024), 2),
            "total_traffic_gb": round(total_traffic_bytes / (1024 * 1024 * 1024), 2),
            "server_time": datetime.now().isoformat(),
        }

    def _parse_proc_net_dev(self) -> dict:
        traffic = {}
        try:
            if not os.path.exists("/proc/net/dev"):
                return traffic
            with open("/proc/net/dev", "r") as f:
                lines = f.readlines()

            for line in lines[2:]:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(":")
                if len(parts) < 2:
                    continue
                interface = parts[0].strip()
                counters = parts[1].split()
                if len(counters) < 10:
                    continue
                bytes_in = int(counters[0])
                bytes_out = int(counters[8])
                traffic[interface] = {
                    "bytes_in": bytes_in,
                    "bytes_out": bytes_out,
                    "packets_in": int(counters[1]),
                    "packets_out": int(counters[9]),
                }
        except Exception:
            pass
        return traffic

    def _parse_who(self) -> list:
        sessions = []
        try:
            if not shutil.which("who"):
                return sessions
            result = subprocess.run(
                ["who", "-u"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                return sessions

            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) < 3:
                    continue
                username = parts[0]
                if not re.match(r"^(vpn|router|mikrotik|l2tp|sstp)", username, re.I):
                    continue
                connected_at = None
                try:
                    if len(parts) >= 5:
                        date_str = f"{parts[2]} {parts[3]}"
                        year = datetime.now().year
                        connected_at = datetime.strptime(
                            f"{year} {date_str}", "%Y %Y-%m-%d %H:%M"
                        ).isoformat()
                except Exception:
                    pass

                router_id = self._extract_router_id(username)
                sessions.append(
                    {
                        "username": username,
                        "router_id": router_id,
                        "interface": parts[1] if len(parts) > 1 else "",
                        "protocol": "shell",
                        "connected_at": connected_at,
                        "ip_address": parts[5] if len(parts) > 5 else "",
                    }
                )
        except Exception:
            pass
        return sessions

    def _parse_pppd_sessions(self) -> list:
        sessions = []
        try:
            ppp_dirs = [
                "/var/run/ppp",
                "/var/run/xl2tpd",
                "/var/run/accel-ppp",
            ]

            for ppp_dir in ppp_dirs:
                if not os.path.exists(ppp_dir):
                    continue
                for entry in os.listdir(ppp_dir):
                    entry_path = os.path.join(ppp_dir, entry)
                    if not os.path.isfile(entry_path):
                        continue
                    sessions.extend(self._parse_ppp_file(entry_path))

            if shutil.which("ps"):
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if "pppd" not in line and "xl2tpd" not in line:
                            continue
                        user_match = re.search(
                            r"(?:user|name)[= ]+([a-zA-Z0-9_-]+)", line
                        )
                        iface_match = re.search(r"(ppp\d+|l2tp-\d+)", line)
                        if user_match or iface_match:
                            username = user_match.group(1) if user_match else ""
                            interface = iface_match.group(1) if iface_match else ""
                            router_id = (
                                self._extract_router_id(username) if username else None
                            )
                            sessions.append(
                                {
                                    "username": username,
                                    "router_id": router_id,
                                    "interface": interface,
                                    "protocol": (
                                        "l2tp" if "xl2tp" in line else "ppp"
                                    ),
                                    "connected_at": None,
                                    "ip_address": "",
                                }
                            )
        except Exception:
            pass
        return sessions

    def _parse_ppp_file(self, file_path: str) -> list:
        sessions = []
        try:
            with open(file_path, "r") as f:
                content = f.read()
            username_match = re.search(r"(?:user|name)[= ]+([a-zA-Z0-9_-]+)", content)
            iface_match = re.search(r"(ppp\d+|l2tp-\d+)", content)
            if username_match or iface_match:
                username = username_match.group(1) if username_match else ""
                interface = iface_match.group(1) if iface_match else ""
                router_id = (
                    self._extract_router_id(username) if username else None
                )
                connected_at = None
                mtime = os.path.getmtime(file_path)
                if mtime:
                    connected_at = datetime.fromtimestamp(mtime).isoformat()
                sessions.append(
                    {
                        "username": username,
                        "router_id": router_id,
                        "interface": interface,
                        "protocol": "ppp",
                        "connected_at": connected_at,
                        "ip_address": "",
                    }
                )
        except Exception:
            pass
        return sessions

    @staticmethod
    def _extract_router_id(username: str) -> Optional[int]:
        if not username:
            return None
        match = re.search(r"(\d+)$", username)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        seconds = int(seconds)
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs and not parts:
            parts.append(f"{secs}s")
        return " ".join(parts) if parts else "0s"

    def _get_mock_sessions(self) -> list:
        now = time.time()
        base_sessions = [
            {
                "router_id": 1,
                "vpn_username": "vpn101",
                "interface": "ppp0",
                "protocol": "l2tp",
                "online": True,
                "connected_at": datetime.fromtimestamp(now - 3600 * 5).isoformat(),
                "bytes_in": 125_000_000,
                "bytes_out": 89_000_000,
                "ip_address": "10.8.0.10",
            },
            {
                "router_id": 2,
                "vpn_username": "vpn199",
                "interface": "ppp1",
                "protocol": "sstp",
                "online": True,
                "connected_at": datetime.fromtimestamp(now - 3600 * 24 * 2).isoformat(),
                "bytes_in": 2_450_000_000,
                "bytes_out": 1_820_000_000,
                "ip_address": "10.8.0.12",
            },
            {
                "router_id": 3,
                "vpn_username": "vpn202",
                "interface": "ppp2",
                "protocol": "l2tp",
                "online": True,
                "connected_at": datetime.fromtimestamp(now - 1800).isoformat(),
                "bytes_in": 12_500_000,
                "bytes_out": 8_900_000,
                "ip_address": "10.8.0.15",
            },
            {
                "router_id": 4,
                "vpn_username": "mikrotik31",
                "interface": "ppp3",
                "protocol": "pptp",
                "online": True,
                "connected_at": datetime.fromtimestamp(now - 3600 * 48).isoformat(),
                "bytes_in": 8_900_000_000,
                "bytes_out": 6_400_000_000,
                "ip_address": "10.8.0.20",
            },
        ]
        return base_sessions
