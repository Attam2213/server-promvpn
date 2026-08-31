import os
import re
import subprocess
import shutil
import time
from datetime import datetime
from typing import Optional


class VpnMonitor:
    def __init__(self, db_session_factory=None):
        self._use_mock = self._should_use_mock()
        self._boot_time = self._get_boot_time()
        self._db_session_factory = db_session_factory

    def set_db_factory(self, db_factory):
        self._db_session_factory = db_factory

    def _should_use_mock(self) -> bool:
        if os.name != "posix":
            return True
        if not os.path.exists("/proc/net/dev"):
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

    def _get_db_router_username_map(self) -> dict:
        mapping = {}
        if not self._db_session_factory:
            return mapping
        try:
            from ..models import Router
            db = self._db_session_factory()
            try:
                routers = db.query(Router).all()
                for r in routers:
                    values = r.values or {}
                    candidates = [
                        values.get("l2tpUser"),
                        values.get("sstpUser"),
                        values.get("pppoeUsername"),
                        values.get("routerName"),
                    ]
                    for u in candidates:
                        if u:
                            mapping[str(u).strip().lower()] = {
                                "router_id": r.id,
                                "router_name": r.name or values.get("routerName") or "Без названия",
                                "values": values,
                            }
            finally:
                db.close()
        except Exception:
            pass
        return mapping

    def _count_db_routers(self) -> int:
        if not self._db_session_factory:
            return 0
        try:
            from ..models import Router
            db = self._db_session_factory()
            try:
                return db.query(Router).count()
            finally:
                db.close()
        except Exception:
            return 0

    def _count_db_profiles(self) -> int:
        if not self._db_session_factory:
            return 0
        try:
            from ..models import Profile
            db = self._db_session_factory()
            try:
                return db.query(Profile).count()
            finally:
                db.close()
        except Exception:
            return 0

    def get_active_sessions(self) -> list:
        username_map = self._get_db_router_username_map()
        if self._use_mock:
            return self._get_mock_sessions()

        sessions = []
        ppp_sessions = self._parse_pppd_sessions()
        xl2tpd_sessions = self._parse_xl2tpd_control()
        ipsec_sessions = self._parse_ipsec_status()
        accel_sessions = self._parse_accel_cmd()
        traffic_map = self._parse_proc_net_dev()

        merged = {}

        def merge(key, data):
            if not key:
                return
            if key not in merged:
                merged[key] = {
                    "router_id": None,
                    "vpn_username": "",
                    "interface": "",
                    "protocol": "",
                    "online": True,
                    "connected_at": None,
                    "bytes_in": 0,
                    "bytes_out": 0,
                    "ip_address": "",
                    "call_id": None,
                    "ike_peers": [],
                }
            for k, v in data.items():
                if v is not None and not merged[key].get(k):
                    merged[key][k] = v
                elif isinstance(v, int) and k in ("bytes_in", "bytes_out"):
                    merged[key][k] = max(merged[key].get(k, 0) or 0, v or 0)

        for ppp in ppp_sessions:
            iface = ppp.get("interface", "")
            username = ppp.get("username", "")
            traffic = traffic_map.get(iface, {})
            merge(
                iface or username or f"ppp-{id(ppp)}",
                {
                    "router_id": ppp.get("router_id"),
                    "vpn_username": username,
                    "interface": iface,
                    "protocol": ppp.get("protocol", "ppp"),
                    "connected_at": ppp.get("connected_at"),
                    "bytes_in": traffic.get("bytes_in", 0),
                    "bytes_out": traffic.get("bytes_out", 0),
                    "ip_address": ppp.get("ip_address", ""),
                },
            )

        for s in xl2tpd_sessions:
            iface = s.get("interface", "")
            username = s.get("username", "")
            traffic = traffic_map.get(iface, {})
            merge(
                iface or username or f"l2tp-{id(s)}",
                {
                    "router_id": s.get("router_id"),
                    "vpn_username": username,
                    "interface": iface,
                    "protocol": "l2tp",
                    "connected_at": s.get("connected_at"),
                    "bytes_in": max(traffic.get("bytes_in", 0), s.get("bytes_in", 0) or 0),
                    "bytes_out": max(traffic.get("bytes_out", 0), s.get("bytes_out", 0) or 0),
                    "ip_address": s.get("ip_address", ""),
                    "call_id": s.get("call_id"),
                },
            )

        for s in accel_sessions:
            iface = s.get("interface", "")
            username = s.get("username", "")
            traffic = traffic_map.get(iface, {})
            merge(
                iface or username or f"sstp-{id(s)}",
                {
                    "router_id": s.get("router_id"),
                    "vpn_username": username,
                    "interface": iface,
                    "protocol": s.get("protocol", "sstp"),
                    "connected_at": s.get("connected_at"),
                    "bytes_in": max(traffic.get("bytes_in", 0), s.get("bytes_in", 0) or 0),
                    "bytes_out": max(traffic.get("bytes_out", 0), s.get("bytes_out", 0) or 0),
                    "ip_address": s.get("ip_address", ""),
                },
            )

        for ike in ipsec_sessions:
            ike_user = ike.get("username") or ike.get("peer_id")
            key = f"ike-{ike_user or ike.get('peer') or id(ike)}"
            if ike_user:
                for existing_key, existing in merged.items():
                    if existing.get("vpn_username") and ike_user.lower() == existing["vpn_username"].lower():
                        existing["ike_peers"] = list(set((existing.get("ike_peers") or []) + [ike.get("peer", "")]))
                        key = None
                        break
            if key:
                merge(
                    key,
                    {
                        "router_id": None,
                        "vpn_username": ike_user or "",
                        "interface": "ipsec",
                        "protocol": "ipsec/ike",
                        "connected_at": ike.get("connected_at"),
                        "bytes_in": ike.get("bytes_in", 0),
                        "bytes_out": ike.get("bytes_out", 0),
                        "ip_address": ike.get("peer", ""),
                        "ike_peers": [ike.get("peer", "")],
                    },
                )

        for iface in sorted(traffic_map.keys()):
            if iface.startswith(("ppp", "sstp")) and iface not in {s.get("interface", "") for s in merged.values()}:
                traffic = traffic_map.get(iface, {})
                merge(
                    iface,
                    {
                        "router_id": None,
                        "vpn_username": "",
                        "interface": iface,
                        "protocol": "ppp",
                        "connected_at": None,
                        "bytes_in": traffic.get("bytes_in", 0),
                        "bytes_out": traffic.get("bytes_out", 0),
                        "ip_address": "",
                    },
                )

        final_sessions = list(merged.values())
        for s in final_sessions:
            uname = (s.get("vpn_username") or "").strip().lower()
            if uname and uname in username_map:
                info = username_map[uname]
                if not s.get("router_id"):
                    s["router_id"] = info["router_id"]
                s["router_name"] = info["router_name"]
                values = info["values"] or {}
                if values.get("lanOctet"):
                    s["lan_subnet"] = f"192.168.{values['lanOctet']}.0/24"
                if values.get("ssid") and values.get("hasWifi") is not False:
                    s["ssid"] = values["ssid"]
            else:
                s["router_name"] = s.get("router_name") or ""
                s["lan_subnet"] = ""
                s["ssid"] = ""
            if s.get("connected_at"):
                try:
                    ts = datetime.fromisoformat(str(s["connected_at"]).replace("Z", "")).timestamp()
                    s["uptime_seconds"] = max(0, int(time.time() - ts))
                    s["uptime_human"] = self._format_uptime(s["uptime_seconds"])
                except Exception:
                    s["uptime_seconds"] = 0
                    s["uptime_human"] = ""
            else:
                s["uptime_seconds"] = 0
                s["uptime_human"] = ""
            sess_bytes_in = s.get("bytes_in") or 0
            sess_bytes_out = s.get("bytes_out") or 0
            s["traffic_mb"] = round((sess_bytes_in + sess_bytes_out) / (1024 * 1024), 2)
            s["traffic_human"] = self._format_traffic_bytes(sess_bytes_in + sess_bytes_out)

        final_sessions.sort(
            key=lambda s: (
                0 if s.get("router_id") else 1,
                -(s.get("uptime_seconds") or 0),
            )
        )
        return final_sessions

    def get_router_status(self, router_id: int, vpn_username: str) -> dict:
        sessions = self.get_active_sessions()
        router_map = self._get_db_router_username_map()
        matched_usernames = {u.lower() for u, info in router_map.items() if info["router_id"] == router_id}

        best_session = None
        best_score = -1
        for session in sessions:
            score = 0
            if session.get("router_id") == router_id:
                score += 100
            if vpn_username and session.get("vpn_username") and session["vpn_username"].lower() == vpn_username.lower():
                score += 80
            if session.get("vpn_username", "").lower() in matched_usernames:
                score += 60
            if score > best_score:
                best_score = score
                best_session = session

        if best_session and best_score > 0:
            return {
                "online": True,
                "router_id": router_id,
                "vpn_username": best_session.get("vpn_username", vpn_username),
                "interface": best_session.get("interface", ""),
                "protocol": best_session.get("protocol", "unknown"),
                "connected_at": best_session.get("connected_at"),
                "bytes_in": best_session.get("bytes_in", 0),
                "bytes_out": best_session.get("bytes_out", 0),
                "ip_address": best_session.get("ip_address", ""),
                "uptime_seconds": best_session.get("uptime_seconds", 0),
                "uptime_human": best_session.get("uptime_human", ""),
                "traffic_mb": best_session.get("traffic_mb", 0),
                "traffic_human": best_session.get("traffic_human", "0 B"),
            }

        info = None
        for u, data in router_map.items():
            if data["router_id"] == router_id:
                info = data
                break
        return {
            "online": False,
            "router_id": router_id,
            "vpn_username": vpn_username or (info and next((u for u, d in router_map.items() if d["router_id"] == router_id), "")),
            "router_name": info["router_name"] if info else "",
            "interface": "",
            "protocol": "",
            "connected_at": None,
            "bytes_in": 0,
            "bytes_out": 0,
            "ip_address": "",
            "uptime_seconds": 0,
            "uptime_human": "",
            "traffic_mb": 0,
            "traffic_human": "0 B",
        }

    def get_server_stats(self) -> dict:
        sessions = self.get_active_sessions()
        online_count = len([s for s in sessions if s.get("online")])
        total_traffic_bytes = sum(
            (s.get("bytes_in") or 0) + (s.get("bytes_out") or 0) for s in sessions
        )
        total_routers = self._count_db_routers()
        total_profiles = self._count_db_profiles()
        offline_count = max(0, total_routers - online_count)

        system_traffic_bytes = 0
        try:
            traffic_map = self._parse_proc_net_dev()
            for iface, data in traffic_map.items():
                if iface.startswith(("ens", "eth", "ppp", "sstp")):
                    system_traffic_bytes += (data.get("bytes_in") or 0) + (data.get("bytes_out") or 0)
        except Exception:
            system_traffic_bytes = total_traffic_bytes

        total_traffic_bytes = max(total_traffic_bytes, system_traffic_bytes)

        return {
            "uptime_seconds": int(time.time() - self._boot_time),
            "uptime_human": self._format_uptime(time.time() - self._boot_time),
            "total_routers": total_routers,
            "total_profiles": total_profiles,
            "online_count": online_count,
            "offline_count": offline_count,
            "total_traffic_bytes": total_traffic_bytes,
            "total_traffic_mb": round(total_traffic_bytes / (1024 * 1024), 2),
            "total_traffic_gb": round(total_traffic_bytes / (1024 * 1024 * 1024), 2),
            "total_traffic_human": self._format_traffic_bytes(total_traffic_bytes),
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

    def _parse_xl2tpd_control(self) -> list:
        sessions = []
        if not shutil.which("xl2tpd-control"):
            return sessions
        try:
            result = subprocess.run(
                ["xl2tpd-control", "status"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.returncode != 0 or not result.stdout:
                return sessions
            output = result.stdout
            current_call = None
            for line in output.splitlines():
                line = line.strip()
                call_match = re.match(r"^call\s+#?\s*(\d+)", line, re.I)
                if call_match:
                    if current_call:
                        sessions.append(current_call)
                    current_call = {
                        "call_id": int(call_match.group(1)),
                        "username": "",
                        "interface": "",
                        "ip_address": "",
                        "connected_at": None,
                        "bytes_in": 0,
                        "bytes_out": 0,
                        "protocol": "l2tp",
                    }
                    continue
                if current_call is None:
                    continue
                kv_match = re.match(r"^([a-zA-Z0-9_-]+)\s*[:=]\s*(.+)$", line)
                if kv_match:
                    key = kv_match.group(1).lower()
                    val = kv_match.group(2).strip()
                    if key in ("username", "name", "login"):
                        current_call["username"] = val.strip().strip("'\"")
                    elif key in ("interface", "ifname", "pppiface"):
                        current_call["interface"] = val.strip()
                    elif key in ("ip", "ip_address", "peer_ip", "remoteip"):
                        current_call["ip_address"] = val.strip()
                    elif key in ("connected", "connected_since", "start_time", "time"):
                        current_call["connected_at"] = self._parse_time_str(val)
                    elif key in ("rx_bytes", "bytes_in", "rxbytes"):
                        current_call["bytes_in"] = int(val)
                    elif key in ("tx_bytes", "bytes_out", "txbytes"):
                        current_call["bytes_out"] = int(val)
            if current_call:
                sessions.append(current_call)
        except Exception:
            pass
        return sessions

    def _parse_ipsec_status(self) -> list:
        sessions = []
        cmd_opts = []
        if shutil.which("ipsec"):
            cmd_opts.append(["ipsec", "status"])
            cmd_opts.append(["ipsec", "trafficstatus"])
        if shutil.which("swanctl"):
            cmd_opts.append(["swanctl", "--list-sas"])
            cmd_opts.append(["swanctl", "--list-conns"])

        for cmd in cmd_opts:
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode != 0 or not result.stdout:
                    continue
                sessions.extend(self._parse_ipsec_output(result.stdout, cmd))
            except Exception:
                pass
        return sessions

    def _parse_ipsec_output(self, output: str, cmd) -> list:
        sessions = []
        try:
            if "swanctl" in (cmd or []) and "--list-sas" in (cmd or []):
                current = None
                for line in output.splitlines():
                    stripped = line.strip()
                    if not stripped:
                        if current:
                            sessions.append(current)
                            current = None
                        continue
                    m = re.match(r"^([\w.-]+)\[\d+]:\s*INSTALLED", stripped) or re.match(r"^([\w.-]+):\s*INSTALLED", stripped)
                    if m:
                        if current:
                            sessions.append(current)
                        current = {
                            "peer_id": m.group(1),
                            "peer": "",
                            "username": m.group(1),
                            "connected_at": None,
                            "bytes_in": 0,
                            "bytes_out": 0,
                        }
                        continue
                    if current is None:
                        continue
                    ip_m = re.search(r"\b(?:remote|other|peer|initiator)\s*=\s*(\d+\.\d+\.\d+\.\d+)", stripped, re.I) or re.search(r"(\d+\.\d+\.\d+\.\d+)", stripped)
                    if ip_m and not current.get("peer"):
                        current["peer"] = ip_m.group(1)
                    rx_m = re.search(r"bytes_i(?:n)?\s*[:=]\s*(\d+)", stripped, re.I) or re.search(r"(\d+)\s*bytes_i", stripped, re.I)
                    if rx_m:
                        current["bytes_in"] = (current.get("bytes_in") or 0) + int(rx_m.group(1))
                    tx_m = re.search(r"bytes_o(?:ut)?\s*[:=]\s*(\d+)", stripped, re.I) or re.search(r"(\d+)\s*bytes_o", stripped, re.I)
                    if tx_m:
                        current["bytes_out"] = (current.get("bytes_out") or 0) + int(tx_m.group(1))
                    est_m = re.search(r"established\s+(\d+)\s*s", stripped, re.I)
                    if est_m:
                        current["connected_at"] = datetime.fromtimestamp(time.time() - int(est_m.group(1))).isoformat()
                if current:
                    sessions.append(current)
                return sessions

            # libreswan/pluto ipsec status parser
            blocks = re.split(r"\n(?=\w+\s*\d+\s*[:#])", output)
            for blk in blocks:
                first = blk.strip().splitlines()
                if not first:
                    continue
                header = first[0]
                peer = ""
                peer_m = re.search(r"(\d+\.\d+\.\d+\.\d+)", header)
                if peer_m:
                    peer = peer_m.group(1)
                username = ""
                user_m = re.search(r"\buser=([\w.-]+)", blk, re.I) or re.search(r"\bclient=([\w.-]+)", blk, re.I) or re.search(r"([\w.-]+)\[\d+\]", blk)
                if user_m:
                    username = user_m.group(1)
                rx_m = re.search(r"BytesIn\s*[:=]\s*(\d+)", blk, re.I) or re.search(r"bytes\.i\s*[:=]\s*(\d+)", blk, re.I)
                tx_m = re.search(r"BytesOut\s*[:=]\s*(\d+)", blk, re.I) or re.search(r"bytes\.o\s*[:=]\s*(\d+)", blk, re.I)
                uptime_m = re.search(r"(\d+)\s*seconds", blk, re.I)
                conn_at = None
                if uptime_m:
                    conn_at = datetime.fromtimestamp(time.time() - int(uptime_m.group(1))).isoformat()
                sessions.append({
                    "peer": peer,
                    "peer_id": username or peer,
                    "username": username,
                    "connected_at": conn_at,
                    "bytes_in": int(rx_m.group(1)) if rx_m else 0,
                    "bytes_out": int(tx_m.group(1)) if tx_m else 0,
                })
        except Exception:
            pass
        return sessions

    def _parse_accel_cmd(self) -> list:
        sessions = []
        cmd = None
        if shutil.which("accel-cmd"):
            cmd = ["accel-cmd", "-H", "127.0.0.1", "-P", "2001", "show", "sessions"]
        elif os.path.exists("/usr/sbin/accel-cmd"):
            cmd = ["/usr/sbin/accel-cmd", "-H", "127.0.0.1", "-P", "2001", "show", "sessions"]
        if not cmd:
            return sessions
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if result.returncode != 0 or not result.stdout:
                return sessions
            raw_lines = [l.rstrip() for l in result.stdout.splitlines()]
            lines = []
            for l in raw_lines:
                stripped = l.strip()
                if not stripped:
                    continue
                if re.fullmatch(r"[\-+| ]+", stripped):
                    continue
                lines.append(stripped)
            if len(lines) <= 1:
                return sessions

            def _split_row(s):
                if "|" in s:
                    return [c.strip() for c in s.split("|")]
                return re.split(r"\s{2,}|\t", s)

            headers_raw = _split_row(lines[0])
            headers = []
            for h in headers_raw:
                hl = h.lower()
                if hl == "ifname":
                    hl = "interface"
                headers.append(hl)
            idx_iface = headers.index("interface") if "interface" in headers else None
            idx_user = headers.index("username") if "username" in headers else -1
            idx_ip = headers.index("ip") if "ip" in headers else (headers.index("calling-sid") if "calling-sid" in headers else None)
            idx_time = headers.index("uptime") if "uptime" in headers else (headers.index("time") if "time" in headers else None)
            idx_rx = headers.index("rx-bytes") if "rx-bytes" in headers else (headers.index("rx") if "rx" in headers else -1)
            idx_tx = headers.index("tx-bytes") if "tx-bytes" in headers else (headers.index("tx") if "tx" in headers else -1)
            idx_proto = headers.index("proto") if "proto" in headers else (headers.index("type") if "type" in headers else -1)
            for line in lines[1:]:
                cols = _split_row(line)
                sess = {
                    "interface": cols[idx_iface].strip() if idx_iface is not None and idx_iface < len(cols) else "",
                    "username": cols[idx_user].strip() if 0 <= idx_user < len(cols) else "",
                    "ip_address": cols[idx_ip].strip() if idx_ip is not None and idx_ip < len(cols) else "",
                    "protocol": "sstp",
                    "connected_at": None,
                    "bytes_in": 0,
                    "bytes_out": 0,
                }
                if 0 <= idx_proto < len(cols):
                    p = cols[idx_proto].strip().lower()
                    if p:
                        sess["protocol"] = p
                if idx_time is not None and 0 <= idx_time < len(cols):
                    ts = self._parse_uptime_str(cols[idx_time].strip())
                    if ts:
                        sess["connected_at"] = datetime.fromtimestamp(ts).isoformat()
                if 0 <= idx_rx < len(cols):
                    try:
                        sess["bytes_in"] = int(self._to_bytes(cols[idx_rx].strip()))
                    except Exception:
                        pass
                if 0 <= idx_tx < len(cols):
                    try:
                        sess["bytes_out"] = int(self._to_bytes(cols[idx_tx].strip()))
                    except Exception:
                        pass
                if sess["interface"] or sess["username"] or sess["ip_address"]:
                    sessions.append(sess)
        except Exception:
            pass
        return sessions

    @staticmethod
    def _to_bytes(val: str) -> int:
        val = val.strip().lower()
        if not val:
            return 0
        units = {"k": 1024, "m": 1024 * 1024, "g": 1024 * 1024 * 1024, "t": 1024 ** 4}
        m = re.match(r"^([\d.]+)\s*([kmgt]?)b?$", val)
        if not m:
            try:
                return int(val)
            except Exception:
                return 0
        num = float(m.group(1))
        u = m.group(2)
        mul = units.get(u, 1)
        return int(num * mul)

    def _parse_uptime_str(self, s: str) -> Optional[float]:
        if not s:
            return None
        s = s.strip()
        total_seconds = 0
        match = re.match(r"^(?:(\d+)[дd]\s*)?(?:(\d+)[чh]\s*)?(?:(\d+)[мm]\s*)?(?:(\d+)[сs]?)?$", s, re.I)
        if match:
            d, h, mi, se = match.groups()
            if d: total_seconds += int(d) * 86400
            if h: total_seconds += int(h) * 3600
            if mi: total_seconds += int(mi) * 60
            if se: total_seconds += int(se)
            if total_seconds > 0:
                return time.time() - total_seconds
        return None

    def _parse_time_str(self, s: str) -> Optional[str]:
        if not s:
            return None
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
            "%H:%M:%S %d.%m.%Y",
        ):
            try:
                return datetime.strptime(s.strip(), fmt).isoformat()
            except Exception:
                continue
        try:
            ts = float(s.strip())
            return datetime.fromtimestamp(ts).isoformat()
        except Exception:
            return None

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
                        if "pppd" not in line and "xl2tpd" not in line and "accel-pppd" not in line:
                            continue
                        user_match = re.search(
                            r"(?:user|name)[= ]+([a-zA-Z0-9_.-]+)", line
                        )
                        iface_match = re.search(r"(ppp\d+|l2tp-\d+|sstp\d+)", line)
                        if user_match or iface_match:
                            username = user_match.group(1) if user_match else ""
                            interface = iface_match.group(1) if iface_match else ""
                            router_id = (
                                self._extract_router_id(username) if username else None
                            )
                            protocol = "sstp" if "accel-ppp" in line else (
                                "l2tp" if "xl2tp" in line else "ppp"
                            )
                            sessions.append(
                                {
                                    "username": username,
                                    "router_id": router_id,
                                    "interface": interface,
                                    "protocol": protocol,
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
            username_match = re.search(r"(?:user|name)[= ]+([a-zA-Z0-9_.-]+)", content)
            iface_match = re.search(r"(ppp\d+|l2tp-\d+|sstp\d+)", content)
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
            parts.append(f"{days}д")
        if hours:
            parts.append(f"{hours}ч")
        if minutes:
            parts.append(f"{minutes}м")
        if secs and not parts:
            parts.append(f"{secs}с")
        return " ".join(parts) if parts else "0с"

    @staticmethod
    def _format_traffic_bytes(num_bytes: int) -> str:
        try:
            num = float(num_bytes or 0)
        except Exception:
            num = 0
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        i = 0
        while num >= 1024 and i < len(units) - 1:
            num /= 1024
            i += 1
        if i == 0:
            return f"{int(num)} {units[i]}"
        return f"{num:.2f} {units[i]}"

    def _get_mock_sessions(self) -> list:
        return []
