import os
import re
import json
from pathlib import Path


NETMASK_PREFIX_MAP = {
    "255.0.0.0": 8,
    "255.255.0.0": 16,
    "255.255.255.0": 24,
    "255.255.255.128": 25,
    "255.255.255.192": 26,
    "255.255.255.224": 27,
    "255.255.255.240": 28,
    "255.255.255.248": 29,
    "255.255.255.252": 30,
}


class ConfigGenerator:
    def __init__(self, schema_path: str = None):
        self.schema = None
        self._load_schema(schema_path)

    def _load_schema(self, schema_path: str = None):
        if schema_path is None:
            schema_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "editable-fields.json",
            )
        schema_path = os.path.abspath(schema_path)
        if os.path.exists(schema_path):
            with open(schema_path, "r", encoding="utf-8") as f:
                self.schema = json.load(f)

    @staticmethod
    def _safe_re_sub(pattern, repl, string, count=0, flags=0):
        return re.sub(
            pattern,
            lambda m, repl_copy=repl: repl_copy,
            string,
            count=count,
            flags=flags,
        )

    def load_template(self, template_name: str) -> str:
        template_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "templates",
        )
        template_path = os.path.join(template_dir, template_name)
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    def _get_template_for_wan(self, wan_type: str, template_dir: str) -> str:
        if wan_type == "pppoe":
            return self.load_template("pppoe.rsc")
        return self.load_template("conff.rsc")

    _LEGACY_L2TP_IPS = {"185.253.182.24", "111.111.111.11"}
    _LEGACY_SSTP_SUFFIXES = (":943", "185.253.182.24:", "111.111.111.111:")

    def _apply_schema_defaults(self, values: dict) -> dict:
        if not self.schema:
            return values or {}
        merged = dict(values or {})

        default_l2tp = None
        default_sstp = None
        for field in self.schema.get("fields", []):
            if field.get("id") == "l2tpServer":
                default_l2tp = field.get("default")
            elif field.get("id") == "sstpServer":
                default_sstp = field.get("default")

        l2tp_current = merged.get("l2tpServer")
        if l2tp_current and default_l2tp:
            if any(legacy in str(l2tp_current) for legacy in self._LEGACY_L2TP_IPS):
                merged["l2tpServer"] = default_l2tp
        sstp_current = merged.get("sstpServer")
        if sstp_current and default_sstp:
            sstp_str = str(sstp_current)
            if any(tag in sstp_str for tag in self._LEGACY_SSTP_SUFFIXES) or sstp_str.endswith(":943"):
                merged["sstpServer"] = default_sstp

        for field in self.schema.get("fields", []):
            field_id = field.get("id")
            if not field_id:
                continue
            field_type = field.get("type", "text")
            default = field.get("default")
            current = merged.get(field_id)
            is_empty = (
                current is None
                or (field_type not in ("checkbox",) and current == "")
            )
            if is_empty and default is not None:
                merged[field_id] = default
        return merged

    def validate(self, values: dict) -> dict:
        values = self._apply_schema_defaults(values)
        errors = {}
        has_wifi = values.get("hasWifi", True) is not False
        l2tp_enabled = values.get("enableL2tp", True) is not False
        sstp_enabled = values.get("enableSstp", True) is not False
        wan_type = values.get("wanType") or "automatic"

        if self.schema:
            for field in self.schema.get("fields", []):
                field_id = field["id"]
                value = values.get(field_id)
                section = field.get("section", "")

                skip_field = (
                    (section == "Wi-Fi" and field_id != "hasWifi" and not has_wifi)
                    or (section == "L2TP" and field_id != "enableL2tp" and not l2tp_enabled)
                    or (section == "SSTP" and field_id != "enableSstp" and not sstp_enabled)
                    or (field_id in ["pppoeUsername", "pppoePassword"] and wan_type != "pppoe")
                    or (
                        field_id
                        in [
                            "staticWanIp",
                            "staticWanNetmask",
                            "staticWanGateway",
                            "staticWanDns1",
                            "staticWanDns2",
                        ]
                        and wan_type != "static"
                    )
                )

                if skip_field:
                    continue

                if field.get("required") and (
                    value == "" or value is None
                ):
                    errors[field_id] = "Поле обязательно."
                    continue

                if field.get("type") == "number" and value != "":
                    is_int = isinstance(value, int) and not isinstance(value, bool)
                    if not is_int:
                        if isinstance(value, str) and not value.isdigit():
                            errors[field_id] = "Введите целое число."
                            continue
                        try:
                            value = int(value)
                        except (ValueError, TypeError):
                            errors[field_id] = "Введите целое число."
                            continue

                    min_val = field.get("min")
                    max_val = field.get("max")
                    if isinstance(min_val, (int, float)) and value < min_val:
                        errors[field_id] = f"Минимум {min_val}."
                        continue
                    if isinstance(max_val, (int, float)) and value > max_val:
                        errors[field_id] = f"Максимум {max_val}."
                        continue

                validation = field.get("validation") or {}
                if validation.get("pattern") and value != "":
                    pattern = re.compile(validation["pattern"])
                    if not pattern.match(str(value)):
                        errors[field_id] = validation.get(
                            "message", "Некорректное значение."
                        )

        home_route = values.get("homeRoute")
        if home_route and not self.is_cidr(home_route):
            errors["homeRoute"] = "Используйте формат 192.168.1.0/24."

        dns_server = values.get("dnsServer")
        if dns_server and not self.is_ipv4(dns_server):
            errors["dnsServer"] = "Введите корректный IPv4 адрес."

        wan_interface = values.get("wanInterface")
        if not wan_interface or not str(wan_interface).strip():
            errors["wanInterface"] = "Укажите WAN интерфейс."

        if wan_type == "static":
            static_wan_ip = values.get("staticWanIp")
            if static_wan_ip and not self.is_ipv4(static_wan_ip):
                errors["staticWanIp"] = "Введите корректный IPv4 адрес."

            static_wan_gateway = values.get("staticWanGateway")
            if static_wan_gateway and not self.is_ipv4(static_wan_gateway):
                errors["staticWanGateway"] = "Введите корректный IPv4 адрес."

            static_wan_dns1 = values.get("staticWanDns1")
            if static_wan_dns1 and not self.is_ipv4(static_wan_dns1):
                errors["staticWanDns1"] = "Введите корректный IPv4 адрес."

            static_wan_dns2 = values.get("staticWanDns2")
            if static_wan_dns2 and not self.is_ipv4(static_wan_dns2):
                errors["staticWanDns2"] = "Введите корректный IPv4 адрес."

        dhcp_start = values.get("dhcpRangeStart")
        dhcp_end = values.get("dhcpRangeEnd")
        if isinstance(dhcp_start, int) and isinstance(dhcp_end, int):
            if dhcp_end < dhcp_start:
                errors["dhcpRangeEnd"] = "Конец пула должен быть больше или равен началу."

        route_primary = values.get("requiredRoutePrimary")
        if route_primary and not self.is_cidr(route_primary):
            errors["requiredRoutePrimary"] = "Используйте формат 192.168.1.0/24."

        route_secondary = values.get("requiredRouteSecondary")
        if route_secondary and not self.is_cidr(route_secondary):
            errors["requiredRouteSecondary"] = "Используйте формат 192.168.1.0/24."

        lan_bridge_ports = self.parse_lines(values.get("lanBridgePorts", ""))
        if len(lan_bridge_ports) == 0:
            errors["lanBridgePorts"] = "Добавьте хотя бы один LAN порт."

        if not l2tp_enabled and not sstp_enabled:
            errors["enableL2tp"] = "Включите хотя бы один протокол туннеля."

        extra_routes = self.parse_lines(values.get("extraRoutes", ""))
        if len(extra_routes) > 0 and not all(self.is_cidr(r) for r in extra_routes):
            errors["extraRoutes"] = "Каждая строка должна быть в формате 192.168.1.0/24."

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }

    def build_config(self, values: dict, template_dir: str = None) -> str:
        values = self._apply_schema_defaults(values)
        config = self._get_template_for_wan(values.get("wanType", "automatic"), template_dir)
        newline = "\r\n" if "\r\n" in config else "\n"

        dns_server_value = (
            self.build_static_wan_dns_servers(values)
            or values.get("dnsServer")
            or self.get_auto_dns_server(values.get("lanOctet"))
        )
        if values.get("wanType") != "static":
            dns_server_value = (
                values.get("dnsServer")
                or self.get_auto_dns_server(values.get("lanOctet"))
            )

        config = config.replace(
            "admin-mac=B8:69:F4:F3:83:71",
            f"admin-mac={self.normalize_mac(values.get('adminMac', ''))}",
        )
        config = config.replace(
            "admin-mac=B8:69:F4:F3:81:82",
            f"admin-mac={self.normalize_mac(values.get('adminMac', ''))}",
        )

        if values.get("hasWifi") is not False:
            config = self._safe_re_sub(
                r"ssid=\S+",
                f"ssid={values.get('ssid', '')}",
                config,
                count=1,
            )
        else:
            config = self.remove_wireless_config(config)

        l2tp_repl = ""
        if values.get("enableL2tp") is not False:
            l2tp_repl = (
                f"/interface l2tp-client{newline}"
                f"add connect-to={values.get('l2tpServer', '')} disabled=no name=vpn "
                f"password={values.get('l2tpPassword', '')} user=\\{newline}"
                f"    {values.get('l2tpUser', '')}{newline}"
            )
        config = self.replace_config_block(
            config,
            "/interface l2tp-client",
            "/interface list",
            l2tp_repl,
        )

        sstp_repl = ""
        if values.get("enableSstp") is not False:
            sstp_repl = (
                f"/interface sstp-client{newline}"
                f"add connect-to={values.get('sstpServer', '')} disabled=no name=sstp_vpn "
                f"password=\\{newline}    {values.get('sstpPassword', '')} "
                f"profile=default-encryption user={values.get('sstpUser', '')}{newline}"
            )
        config = self.replace_config_block(
            config,
            "/interface sstp-client",
            "/interface bridge port",
            sstp_repl,
        )

        config = self.replace_config_block(
            config,
            "/interface bridge port",
            "/ip neighbor discovery-settings",
            f"/interface bridge port{newline}{self.build_bridge_ports(values, newline)}{newline}",
        )

        config = self.apply_wan_mode(config, values, newline)

        if values.get("hasWifi") is not False:
            wifi_pw = values.get("wifiPassword", "")
            wpa_repl = f"wpa-pre-shared-key={wifi_pw} \\{newline}    wpa2-pre-shared-key={wifi_pw}"
            config = self._safe_re_sub(
                r"wpa-pre-shared-key=[^\s]+ \\\r?\n\s+wpa2-pre-shared-key=\S+",
                wpa_repl,
                config,
                count=1,
            )

        lan_octet = values.get("lanOctet", "")
        prometey_octet = values.get("prometeyOctet", "")
        config = config.replace("192.168.актет.", f"192.168.{lan_octet}.")
        config = config.replace("192.168.актетт.", f"192.168.{prometey_octet}.")

        default_dns = values.get("dnsServer") or self.get_auto_dns_server(lan_octet)
        config = self._safe_re_sub(
            r"dns-server=\d{1,3}(?:\.\d{1,3}){3}",
            f"dns-server={default_dns}",
            config,
            count=1,
        )

        dns_servers_line = f" servers={dns_server_value}" if dns_server_value else ""
        config = self._safe_re_sub(
            r"/ip dns\r?\nset allow-remote-requests=yes(?: servers=[^\r\n]+)?",
            f"/ip dns{newline}set allow-remote-requests=yes{dns_servers_line}",
            config,
            count=1,
        )

        lan_interface = values.get("lanInterface", "ether2")
        network_repl = f"add address=192.168.{lan_octet}.1/24 comment=defconf interface={lan_interface} network=\\"
        config = self._safe_re_sub(
            r"add address=192\.168\.\d{1,3}\.1\/24 comment=defconf interface=\S+ network=\\",
            network_repl,
            config,
            count=1,
        )

        dhcp_start = values.get("dhcpRangeStart", "")
        dhcp_end = values.get("dhcpRangeEnd", "")
        config = self._safe_re_sub(
            r"add name=dhcp ranges=192\.168\.\d{1,3}\.\d{1,3}-192\.168\.\d{1,3}\.\d{1,3}",
            f"add name=dhcp ranges=192.168.{lan_octet}.{dhcp_start}-192.168.{lan_octet}.{dhcp_end}",
            config,
            count=1,
        )

        routes_block = self.build_routes(values, newline)
        config = self._safe_re_sub(
            r"/ip route\r?\n[\s\S]*?\r?\n/system clock",
            f"/ip route{newline}{routes_block}{newline}/system clock",
            config,
            count=1,
        )

        return self._strip_comment_lines(config)

    def build_routes(self, values: dict, newline: str) -> str:
        blocks = []
        extra_routes = self.parse_lines(values.get("extraRoutes", ""))

        if values.get("wanType") == "static":
            blocks.append(f"add distance=1 gateway={values.get('staticWanGateway', '')}")

        blocks.extend(
            self.build_dual_route_lines(values.get("requiredRoutePrimary", ""), values)
        )
        blocks.extend(self.build_dual_route_lines(values.get("homeRoute", ""), values))
        blocks.extend(
            self.build_dual_route_lines(
                f"192.168.{values.get('prometeyOctet', '')}.0/24", values
            )
        )
        blocks.extend(
            self.build_dual_route_lines(values.get("requiredRouteSecondary", ""), values)
        )

        if len(extra_routes) > 0:
            for route in extra_routes:
                blocks.extend(self.build_dual_route_lines(route, values))

        return newline.join(blocks)

    def build_bridge_ports(self, values: dict, newline: str) -> str:
        ports = self.parse_lines(values.get("lanBridgePorts", ""))
        if values.get("hasWifi") is not False:
            ports.append("wlan1")
        return newline.join(
            f"add bridge=bridge comment=defconf interface={port}" for port in ports
        )

    def build_dual_route_lines(self, route: str, values: dict) -> list:
        lines = []
        if not route:
            return lines
        if values.get("enableL2tp") is not False:
            lines.append(f"add distance=1 dst-address={route} gateway=vpn")
        if values.get("enableSstp") is not False:
            lines.append(f"add distance=1 dst-address={route} gateway=sstp_vpn")
        return lines

    def build_file_name(self, values: dict) -> str:
        octet = str(values.get("lanOctet", "")).zfill(3)
        safe_name = (
            str(values.get("routerName") or "mikrotik")
            .strip()
            .lower()
        )
        safe_name = re.sub(r"[^a-z0-9а-яё_-]+", "-", safe_name, flags=re.IGNORECASE)
        safe_name = re.sub(r"-+", "-", safe_name)
        safe_name = safe_name.strip("-")
        return f"{safe_name or 'mikrotik'}-{octet}.rsc"

    def get_dhcp_range_preview(self, values: dict) -> str:
        octet = values.get("lanOctet", "X")
        start = values.get("dhcpRangeStart", "start")
        end = values.get("dhcpRangeEnd", "end")
        return f"192.168.{octet}.{start} - 192.168.{octet}.{end}"

    @staticmethod
    def get_auto_dns_server(lan_octet) -> str:
        return f"192.168.{lan_octet}.1"

    def apply_wan_mode(self, config: str, values: dict, newline: str) -> str:
        wan_interface = values.get("wanInterface", "ether1")

        if values.get("wanType") == "pppoe":
            pppoe_repl = (
                f"/interface pppoe-client{newline}"
                f"add add-default-route=yes disabled=no interface={wan_interface} "
                f"name=pppoe-out1 \\{newline}    "
                f"password={values.get('pppoePassword', '')} use-peer-dns=yes "
                f"user={values.get('pppoeUsername', '')}{newline}"
            )
            config = self.replace_config_block(
                config,
                "/interface pppoe-client",
                "/interface l2tp-client",
                pppoe_repl,
            )
            config = self.remove_config_block(
                config, "/ip dhcp-client", "/ip dhcp-server network"
            )
            config = self._safe_re_sub(
                r"add comment=defconf interface=\S+ list=WAN",
                f"add comment=defconf interface={wan_interface} list=WAN",
                config,
                count=1,
            )
            return config

        config = self.remove_config_block(
            config, "/interface pppoe-client", "/interface l2tp-client"
        )
        config = self._safe_re_sub(
            r"add comment=defconf interface=\S+ list=WAN",
            f"add comment=defconf interface={wan_interface} list=WAN",
            config,
            count=1,
        )

        if values.get("wanType") == "automatic" or values.get("wanType") is None:
            config = self._safe_re_sub(
                r"/ip dhcp-client\r?\nadd comment=defconf dhcp-options=hostname,clientid(?: disabled=no)? interface=\S+",
                f"/ip dhcp-client{newline}add comment=defconf dhcp-options=hostname,clientid disabled=no interface={wan_interface}",
                config,
                count=1,
            )
            return config

        config = self.remove_config_block(
            config, "/ip dhcp-client", "/ip dhcp-server network"
        )
        static_cidr = self.build_static_wan_cidr(values)
        ip_addr_repl = (
            f"/ip address{newline}"
            f"add address={static_cidr} interface={wan_interface}{newline}"
        )
        config = self._safe_re_sub(
            r"/ip address\r?\n",
            ip_addr_repl,
            config,
            count=1,
        )
        return config

    def build_static_wan_cidr(self, values: dict) -> str:
        return f"{values.get('staticWanIp', '')}/{self.convert_netmask_to_prefix(values.get('staticWanNetmask', ''))}"

    @staticmethod
    def build_static_wan_dns_servers(values: dict) -> str:
        return ",".join(
            filter(None, [values.get("staticWanDns1", ""), values.get("staticWanDns2", "")])
        )

    @staticmethod
    def convert_netmask_to_prefix(netmask: str) -> int:
        return NETMASK_PREFIX_MAP.get(netmask, 24)

    @staticmethod
    def parse_lines(value) -> list:
        return [
            line.strip()
            for line in re.split(r"\r?\n", str(value or ""))
            if line.strip()
        ]

    def _strip_comment_lines(self, text: str) -> str:
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = [
            line for line in re.split(r"\r?\n", text) if not line.strip().startswith("#")
        ]
        result = newline.join(lines)
        result = self._safe_re_sub(r"^\s*[\r\n]+", "", result)
        return result

    def remove_wireless_config(self, config: str) -> str:
        config = self._safe_re_sub(
            r"/interface wireless\r?\n[\s\S]*?(?=/interface (?:pppoe-client|l2tp-client)\r?\n)",
            "",
            config,
            count=1,
        )
        config = self._safe_re_sub(
            r"/interface wireless security-profiles\r?\n[\s\S]*?(?=/ip pool\r?\n)",
            "",
            config,
            count=1,
        )
        config = self._safe_re_sub(
            r"^add bridge=bridge comment=defconf interface=wlan1\r?\n?",
            "",
            config,
            count=1,
            flags=re.MULTILINE,
        )
        return config

    def remove_config_block(self, config: str, start_marker: str, end_marker: str) -> str:
        return self.replace_config_block(config, start_marker, end_marker, "")

    def replace_config_block(
        self, config: str, start_marker: str, end_marker: str, replacement: str
    ) -> str:
        escaped_start = re.escape(start_marker)
        escaped_end = re.escape(end_marker)
        pattern = re.compile(
            f"{escaped_start}\\r?\\n[\\s\\S]*?(?={escaped_end}\\r?\\n)", re.MULTILINE
        )
        return pattern.sub(lambda m: replacement, config, count=1)

    @staticmethod
    def normalize_mac(value) -> str:
        return str(value).upper()

    @staticmethod
    def is_ipv4(value) -> bool:
        parts = str(value).strip().split(".")
        if len(parts) != 4:
            return False
        for part in parts:
            if not re.match(r"^\d+$", part):
                return False
            number = int(part)
            if number < 0 or number > 255:
                return False
        return True

    def is_cidr(self, value) -> bool:
        match = re.match(
            r"^(\d{1,3}(?:\.\d{1,3}){3})/(\d{1,2})$", str(value).strip()
        )
        if not match:
            return False
        return self.is_ipv4(match.group(1)) and 0 <= int(match.group(2)) <= 32
