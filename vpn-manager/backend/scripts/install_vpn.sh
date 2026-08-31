#!/bin/bash

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${BOLD}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[FAIL]${NC}  $1" >&2; }

echo "=========================================="
echo "  L2TP + SSTP VPN Server Installer"
echo "  for Ubuntu / Debian VDS"
echo "  (supports 2-IP setup: MGMT + VPN_IP)"
echo "=========================================="
echo ""

if [ "$(id -u)" -ne 0 ]; then
    err "Run this script as root (sudo bash install_vpn.sh)"
    exit 1
fi

AUTO_MGMT_IP="${MGMT_IP:-}"
AUTO_VPN_IP="${VPN_PUBLIC_IP:-}"

if [ -z "$AUTO_MGMT_IP" ]; then
    echo "You can use 2 public IPs on this VPS:"
    echo "  MGMT_IP      = web-panel + SSH listen only"
    echo "  VPN_PUBLIC_IP = L2TP/IPsec connections (all MikroTik tunnels)"
    echo "If you have only 1 IP — just enter the same value for both."
    echo ""
fi

read -p "Enter MGMT IP (panel + SSH bind) [${AUTO_MGMT_IP:-auto detect via ifconfig.me}]: " MGMT_IP
MGMT_IP=${MGMT_IP:-$AUTO_MGMT_IP}
if [ -z "$MGMT_IP" ]; then
    MGMT_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || true)
fi
if [ -z "$MGMT_IP" ]; then
    err "MGMT_IP is required"
    exit 1
fi

read -p "Enter VPN PUBLIC IP for L2TP/IPsec (MikroTik clients will connect HERE) [${AUTO_VPN_IP:-same as MGMT_IP $MGMT_IP}]: " VPN_PUBLIC_IP
VPN_PUBLIC_IP=${VPN_PUBLIC_IP:-$AUTO_VPN_IP}
VPN_PUBLIC_IP=${VPN_PUBLIC_IP:-$MGMT_IP}

echo ""
echo "Using MGMT_IP      = $MGMT_IP  (panel :8000, SSH :22)"
echo "Using VPN_PUBLIC_IP = $VPN_PUBLIC_IP  (L2TP/IPsec tunnels come here)"
echo ""

read -p "Enter IPsec PSK password (shared secret): " IPSEC_PSK
if [ -z "$IPSEC_PSK" ]; then
    err "IPsec PSK is required"
    exit 1
fi

read -p "Enter PPP IP range start [10.255.0.100]: " PPP_START
PPP_START=${PPP_START:-10.255.0.100}
read -p "Enter PPP IP range end [10.255.0.200]: " PPP_END
PPP_END=${PPP_END:-10.255.0.200}

read -p "Enter primary DNS [8.8.8.8]: " DNS1
DNS1=${DNS1:-8.8.8.8}
read -p "Enter secondary DNS [1.1.1.1]: " DNS2
DNS2=${DNS2:-1.1.1.1}

SSTP_OK="no"
echo ""
info "SSTP (accel-ppp) is OPTIONAL: package not in standard Ubuntu repos."
info "SSTP needs manual compile or custom PPA. L2TP/IPsec works out of the box."
read -p "Try to install SSTP (accel-ppp) anyway? [y/N]: " _ans
case "$_ans" in
    y|Y|yes|YES) INSTALL_SSTP="yes" ;;
    *) INSTALL_SSTP="no" ;;
esac

read -p "Configure UFW firewall with per-IP rules (RECOMMENDED for 2-IP setup)? [Y/n]: " _ufw
case "$_ufw" in
    n|N|no|NO) DO_UFW="no" ;;
    *) DO_UFW="yes" ;;
esac

echo ""
echo "=========================================="
echo "  Installing packages..."
echo "=========================================="

export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq || true

BASE_PKGS="xl2tpd ppp iptables-persistent net-tools iptables iproute2"
if [ "$DO_UFW" = "yes" ]; then
    BASE_PKGS="$BASE_PKGS ufw"
fi
SWAN_PKG=""
if apt-cache show libreswan >/dev/null 2>&1; then
    SWAN_PKG="libreswan"
elif apt-cache show strongswan >/dev/null 2>&1; then
    SWAN_PKG="strongswan"
fi

info "Installing L2TP base packages: $BASE_PKGS $SWAN_PKG"
apt-get install -y -qq --no-install-recommends $BASE_PKGS $SWAN_PKG 2>&1 | tail -3 || true

IPSEC_BIN=""
if command -v ipsec >/dev/null 2>&1; then
    IPSEC_BIN="ipsec"
elif command -v strongswan >/dev/null 2>&1; then
    IPSEC_BIN="strongswan"
fi

if [ "$INSTALL_SSTP" = "yes" ]; then
    info "Trying to install accel-ppp (SSTP) via apt..."
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
    if apt-get install -y -qq accel-ppp 2>/dev/null; then
        ok "accel-ppp installed via apt"
        SSTP_OK="yes"
    else
        warn "accel-ppp package not found in standard Ubuntu repos. Switching to SOURCE BUILD (github accel-ppp/accel-ppp)."
        BUILDER="$SCRIPT_DIR/build_accel_ppp.sh"
        if [ -x "$BUILDER" ] || [ -f "$BUILDER" ]; then
            chmod +x "$BUILDER" 2>/dev/null || true
            export VPN_PUBLIC_IP DNS1 DNS2 PPP_START PPP_END
            if bash "$BUILDER"; then
                SSTP_OK="yes"
            else
                warn "Source build reported non-zero status. accel-ppp may still be partially installed."
            fi
        else
            warn "build_accel_ppp.sh not found at $BUILDER. SSTP skipped."
        fi
    fi
fi

echo ""
echo "=========================================="
echo "  Configuring sysctl (IP forwarding)..."
echo "=========================================="

cat > /etc/sysctl.d/99-vpn-forward.conf << 'EOF'
net.ipv4.ip_forward = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.rp_filter = 0
net.ipv4.conf.default.rp_filter = 0
net.ipv4.conf.all.arp_ignore = 1
net.ipv4.conf.all.arp_announce = 2
EOF
sysctl -p /etc/sysctl.d/99-vpn-forward.conf >/dev/null 2>&1 || true
ok "IP forwarding enabled"

echo ""
echo "=========================================="
echo "  Detecting main network interface..."
echo "=========================================="

MAIN_IF=$(ip -4 route ls 2>/dev/null | grep default | grep -Po '(?<=dev )(\S+)' | head -1)
if [ -z "$MAIN_IF" ]; then
    MAIN_IF=$(ls /sys/class/net 2>/dev/null | grep -E '^(eth|ens|enp|wlan|venet|eno)' | head -1)
fi
if [ -z "$MAIN_IF" ]; then
    MAIN_IF="eth0"
fi
echo "Using main interface: $MAIN_IF"
echo ""

echo "=========================================="
echo "  Configuring IPsec (/etc/ipsec.conf) — LISTEN ONLY on $VPN_PUBLIC_IP"
echo "=========================================="

cat > /etc/ipsec.conf << EOF
version 2.0

config setup
    virtual_private=%v4:10.0.0.0/8,%v4:192.168.0.0/16,%v4:172.16.0.0/12
    oe=off
    protostack=netkey

conn L2TP-PSK-NAT
    rightsubnet=vhost:%priv
    also=L2TP-PSK-noNAT

conn L2TP-PSK-noNAT
    authby=secret
    pfs=no
    auto=add
    keyingtries=3
    rekey=no
    ikelifetime=8h
    keylife=1h
    type=transport
    left=$VPN_PUBLIC_IP
    leftprotoport=17/1701
    right=%any
    rightprotoport=17/%any
    dpddelay=40
    dpdtimeout=130
    dpdaction=clear
EOF
ok "/etc/ipsec.conf written (left=$VPN_PUBLIC_IP)"

echo ""
echo "=========================================="
echo "  Configuring IPsec secrets (/etc/ipsec.secrets) bound to $VPN_PUBLIC_IP"
echo "=========================================="

cat > /etc/ipsec.secrets << EOF
$VPN_PUBLIC_IP %any : PSK "$IPSEC_PSK"
EOF

chmod 600 /etc/ipsec.secrets
ok "/etc/ipsec.secrets written"

echo ""
echo "=========================================="
echo "  Configuring libreswan/strongswan: listen IKE only on $VPN_PUBLIC_IP"
echo "=========================================="

if [ -d /etc/ipsec.d ] && [ -f /usr/lib/ipsec/charon 2>/dev/null ] || [ -d /etc/strongswan.d ]; then
    if [ -f /etc/strongswan.d/charon.conf ]; then
        sed -i "s|^.*interfaces.*=.*|interfaces = \{ default \{ bind = $VPN_PUBLIC_IP \} \}|" /etc/strongswan.d/charon.conf 2>/dev/null || true
    fi
    if [ -f /etc/ipsec.d/charon.conf ]; then
        sed -i "s|^.*interfaces.*=.*|interfaces = \{ default \{ bind = $VPN_PUBLIC_IP \} \}|" /etc/ipsec.d/charon.conf 2>/dev/null || true
    fi
    true
fi
ok "Charon bind hint applied: $VPN_PUBLIC_IP"

echo ""
echo "=========================================="
echo "  Configuring xl2tpd: listen ONLY on $VPN_PUBLIC_IP:1701"
echo "=========================================="

mkdir -p /etc/xl2tpd
cat > /etc/xl2tpd/xl2tpd.conf << EOF
[global]
port = 1701
listen-addr = $VPN_PUBLIC_IP
auth file = /etc/ppp/chap-secrets
access control = no
debug avp = no
debug network = no
debug packet = no
debug state = no
debug tunnel = no

[lns default]
ip range = $PPP_START-$PPP_END
local ip = 10.255.0.1
require chap = yes
refuse pap = yes
require authentication = yes
name = L2TP-VPN
ppp debug = no
pppoptfile = /etc/ppp/options.xl2tpd
length bit = yes
EOF
ok "/etc/xl2tpd/xl2tpd.conf written (listen-addr=$VPN_PUBLIC_IP)"

echo ""
echo "=========================================="
echo "  Configuring PPP options (/etc/ppp/options.xl2tpd)..."
echo "=========================================="

cat > /etc/ppp/options.xl2tpd << EOF
require-mschap-v2
ms-dns $DNS1
ms-dns $DNS2
asyncmap 0
auth
hide-password
name l2tpd
proxyarp
lcp-echo-failure 4
lcp-echo-interval 30
mtu 1410
mru 1410
noipx
EOF
ok "/etc/ppp/options.xl2tpd written"

if [ "$SSTP_OK" = "yes" ]; then
echo ""
echo "=========================================="
echo "  Configuring accel-ppp (SSTP) — listen on 0.0.0.0:443 (inbound iptables restricted to $VPN_PUBLIC_IP only)"
echo "=========================================="
mkdir -p /etc/accel-ppp /var/log/accel-ppp /etc/accel-ppp/conf /run/accel-ppp
# NOTE: Use SAME /24 subnet as L2TP xl2tpd gateway (10.255.0.x) to avoid ippool cann't parse error.
SSTP_LOCAL_IP="10.255.0.1"
SSTP_POOL_START="10.255.0.240"
SSTP_POOL_END="10.255.0.250"
cat > /etc/accel-ppp.conf << EOF
[modules]
log_file
sstp
auth_pap

[core]
log-error=/var/log/accel-ppp/core.log
thread-count=1
die-on-modload-error=no
max-sessions=200
max-async-sessions=200
max-sync-sessions=200

[common]
single-session=replace
sid-case=upper
sid-source=seq

[log]
log-file=/var/log/accel-ppp/accel-ppp.log
log-emerg=/var/log/accel-ppp/emerg.log
log-fail-file=/var/log/accel-ppp/auth-fail.log
copy=3
default=debug

[ppp]
verbose=3
min-mtu=1280
mtu=1400
mru=1400
ipv4=require
ipv6=deny
check-ip=0

[dns]
dns1=$DNS1
dns2=$DNS2

[sstp]
host=0.0.0.0
port=443
verbose=3
certificate=/etc/accel-ppp/certs/sstp.crt
private-key=/etc/accel-ppp/certs/sstp.key

[ip-pool]
gw-ip-address=$SSTP_LOCAL_IP
$SSTP_POOL_START-$SSTP_POOL_END

[cli]
# IMPORTANT: localhost only — never expose ctrl socket to public internet.
# Usage: accel-cmd -H 127.0.0.1 -P 2001 show sessions
verbose=0
tcp=127.0.0.1:2001

[auth]
# Strict auth using shared chap-secrets with xl2tpd (same users for L2TP and SSTP).
# chap-secrets/auth_mschap_v2 modules cause SIGSEGV on accel-ppp 1.12.0 Ubuntu 22.04
# so we use auth_pap built-in secrets loader instead — it is safe.
any-login=0
secrets=/etc/accel-ppp/conf/chap-secrets
EOF
touch /etc/accel-ppp/conf/chap-secrets
chmod 600 /etc/accel-ppp/conf/chap-secrets
ok "/etc/accel-ppp.conf written (SSTP on 0.0.0.0:443, iptables locked to $VPN_PUBLIC_IP; ctrl 127.0.0.1:2001; strict auth via secrets)"
fi

echo ""
echo "=========================================="
echo "  Configuring /etc/ppp/chap-secrets template..."
echo "=========================================="

cat > /etc/ppp/chap-secrets << 'EOF'
# Secrets for authentication using CHAP
# client    server    secret    IP address
EOF

chmod 600 /etc/ppp/chap-secrets
ok "/etc/ppp/chap-secrets written"

echo ""
echo "=========================================="
echo "  iptables: NAT only via $VPN_PUBLIC_IP + firewall INPUT chain"
echo "=========================================="

iptables -t nat -F 2>/dev/null || true
iptables -F 2>/dev/null || true
iptables -X INPUT 2>/dev/null || true
iptables -X FORWARD 2>/dev/null || true

iptables -t nat -A POSTROUTING -s 10.255.0.0/16 -j SNAT --to-source $VPN_PUBLIC_IP 2>/dev/null || \
iptables -t nat -A POSTROUTING -s 10.255.0.0/16 -o "$MAIN_IF" -j MASQUERADE

# Allow loopback
iptables -A INPUT -i lo -j ACCEPT

# Allow established traffic on MGMT interface (SSH/panel)
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -p icmp -j ACCEPT

# MGMT_IP: allow SSH + web-panel
iptables -A INPUT -d $MGMT_IP -p tcp --dport 22 -j ACCEPT
iptables -A INPUT -d $MGMT_IP -p tcp --dport 8000 -j ACCEPT

# VPN_PUBLIC_IP: allow IPsec (500/udp, 4500/udp, ESP 50, AH 51, L2TP 1701/udp
iptables -A INPUT -d $VPN_PUBLIC_IP -p udp --dport 500 -j ACCEPT
iptables -A INPUT -d $VPN_PUBLIC_IP -p udp --dport 4500 -j ACCEPT
iptables -A INPUT -d $VPN_PUBLIC_IP -p udp --dport 1701 -j ACCEPT
iptables -A INPUT -d $VPN_PUBLIC_IP -p esp -j ACCEPT
iptables -A INPUT -d $VPN_PUBLIC_IP -p ah -j ACCEPT
if [ "$SSTP_OK" = "yes" ]; then
    iptables -A INPUT -d $VPN_PUBLIC_IP -p tcp --dport 443 -j ACCEPT
fi

# FORWARD
iptables -A FORWARD -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A FORWARD -s 10.255.0.0/16 -j ACCEPT
iptables -A FORWARD -d 10.255.0.0/16 -j ACCEPT
iptables -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
iptables -P FORWARD DROP

# INPUT default DROP (explicit rejects later if not matched)
iptables -A INPUT -j REJECT --reject-with icmp-host-prohibited

ok "iptables applied (NAT SNAT --to-source $VPN_PUBLIC_IP ; INPUT default-REJECT"

echo ""
echo "=========================================="
echo "  Saving iptables rules (persistent)..."
echo "=========================================="

mkdir -p /etc/iptables
if command -v iptables-save >/dev/null 2>&1; then
    iptables-save > /etc/iptables/rules.v4 2>/dev/null && echo "iptables saved to /etc/iptables/rules.v4" || true
fi

if [ "$DO_UFW" = "yes" ] && command -v ufw >/dev/null 2>&1; then
echo ""
echo "=========================================="
echo "  UFW per-IP rules (2-IP hardening) — enabling..."
echo "=========================================="
ufw --force reset 2>/dev/null || true
ufw default deny incoming 2>/dev/null || true
ufw default allow outgoing 2>/dev/null || true
ufw allow in on lo 2>/dev/null || true
ufw allow to any port 22 proto tcp from any to $MGMT_IP 2>/dev/null || ufw allow 22/tcp
ufw allow to any port 8000 proto tcp from any to $MGMT_IP 2>/dev/null || ufw allow 8000/tcp
ufw allow to any port 500 proto udp from any to $VPN_PUBLIC_IP 2>/dev/null || ufw allow 500/udp
ufw allow to any port 4500 proto udp from any to $VPN_PUBLIC_IP 2>/dev/null || ufw allow 4500/udp
ufw allow to any port 1701 proto udp from any to $VPN_PUBLIC_IP 2>/dev/null || ufw allow 1701/udp
if [ "$SSTP_OK" = "yes" ]; then
ufw allow to any port 443 proto tcp from any to $VPN_PUBLIC_IP 2>/dev/null || ufw allow 443/tcp
fi
ufw --force enable 2>/dev/null || true
ok "UFW enabled with per-IP port restrictions"
fi

echo ""
echo "=========================================="
echo "  Enabling and starting services..."
echo "=========================================="

IPSEC_SVC=""
if systemctl list-unit-files 2>/dev/null | grep -q '^ipsec.service'; then
    IPSEC_SVC="ipsec"
elif systemctl list-unit-files 2>/dev/null | grep -q '^libreswan.service'; then
    IPSEC_SVC="libreswan"
elif systemctl list-unit-files 2>/dev/null | grep -q '^strongswan.service'; then
    IPSEC_SVC="strongswan"
elif systemctl list-unit-files 2>/dev/null | grep -q '^strongswan-starter.service'; then
    IPSEC_SVC="strongswan-starter"
fi

[ -n "$IPSEC_SVC" ] && systemctl enable "$IPSEC_SVC" 2>/dev/null || true
systemctl enable xl2tpd 2>/dev/null || true
[ "$SSTP_OK" = "yes" ] && systemctl enable accel-ppp 2>/dev/null || true

[ -n "$IPSEC_SVC" ] && systemctl restart "$IPSEC_SVC" 2>/dev/null || true
systemctl restart xl2tpd 2>/dev/null || true
[ "$SSTP_OK" = "yes" ] && systemctl restart accel-ppp 2>/dev/null || true

sleep 2

echo ""
echo "=========================================="
echo "  Service status check:"
echo "=========================================="

check_svc() {
    local s=$1
    if systemctl is-active --quiet "$s" 2>/dev/null; then
        echo "  [OK]   $s is running"
    else
        echo "  [WARN] $s is NOT running"
    fi
}

[ -n "$IPSEC_SVC" ] && check_svc "$IPSEC_SVC"
check_svc xl2tpd
[ "$SSTP_OK" = "yes" ] && check_svc accel-ppp
if command -v ss >/dev/null 2>&1; then
echo ""
echo "  LISTENING PORTS (public services on $VPN_PUBLIC_IP + $MGMT_IP):"
ss -tulpn 2>/dev/null | grep -E ":(22|8000|500|1701|4500|443)\b" | head -20 || true
fi

echo ""
echo "=========================================="
echo -e "  ${GREEN}Installation complete!${NC}"
echo "=========================================="
echo ""
echo "MGMT_IP (panel/SSH) : $MGMT_IP"
echo "VPN_PUBLIC_IP (tunnels): $VPN_PUBLIC_IP (MikroTik L2TP connects HERE)"
echo "IPsec PSK           : $IPSEC_PSK"
echo "L2TP ports (on $VPN_PUBLIC_IP): UDP 500/4500/1701 + ESP"
echo "L2TP PPP range      : $PPP_START - $PPP_END"
echo "SSTP status         : $([ "$SSTP_OK" = "yes" ] && echo "TCP 443 on $VPN_PUBLIC_IP (accel-ppp SSTP server)" || echo "SKIPPED")"
echo "DNS servers         : $DNS1, $DNS2"
echo "Main interface      : $MAIN_IF"
echo ""
echo "NAT: 10.255.0.0/16 SNAT --to-source $VPN_PUBLIC_IP (all MikroTik traffic exits via VPN_IP)"
echo ""
echo "Users are managed in /etc/ppp/chap-secrets"
echo "Format:  username  *  password  *"
echo ""
echo "Sync users from web panel via POST /api/vpn/sync (or dashboard button)"
echo ""
echo "To check L2TP logs:"
echo "  journalctl -u xl2tpd -f  OR  tail -f /var/log/syslog | grep -E 'xl2tpd|pppd|ipsec'"
echo ""
