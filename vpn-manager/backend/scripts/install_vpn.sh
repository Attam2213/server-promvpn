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
echo "=========================================="
echo ""

if [ "$(id -u)" -ne 0 ]; then
    err "Run this script as root (sudo bash install_vpn.sh)"
    exit 1
fi

read -p "Enter public IP of this VDS: " PUBLIC_IP
if [ -z "$PUBLIC_IP" ]; then
    err "Public IP is required"
    exit 1
fi

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

SSTP_START="10.255.1.100"
SSTP_END="10.255.1.200"
INSTALL_SSTP="no"
echo ""
info "SSTP (accel-ppp) is OPTIONAL: package not in standard Ubuntu repos."
info "SSTP needs manual compile or custom PPA. L2TP/IPsec works out of the box."
read -p "Try to install SSTP (accel-ppp) anyway? [y/N]: " _ans
case "$_ans" in
    y|Y|yes|YES) INSTALL_SSTP="yes" ;;
esac

echo ""
echo "=========================================="
echo "  Installing packages..."
echo "=========================================="

export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq || true

BASE_PKGS="xl2tpd ppp iptables-persistent net-tools iptables"
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

SSTP_OK="no"
if [ "$INSTALL_SSTP" = "yes" ]; then
    info "Trying to install accel-ppp (SSTP)..."
    if apt-get install -y -qq accel-ppp 2>/dev/null; then
        ok "accel-ppp installed"
        SSTP_OK="yes"
    else
        warn "accel-ppp package not found in standard repos. SSTP skipped."
        warn "To enable SSTP manually: add custom repo or build accel-ppp from sources."
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
EOF
sysctl -p /etc/sysctl.d/99-vpn-forward.conf >/dev/null 2>&1 || true
ok "IP forwarding enabled"

echo ""
echo "=========================================="
echo "  Configuring IPsec (/etc/ipsec.conf)..."
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
    left=$PUBLIC_IP
    leftprotoport=17/1701
    right=%any
    rightprotoport=17/%any
    dpddelay=40
    dpdtimeout=130
    dpdaction=clear
EOF
ok "/etc/ipsec.conf written"

echo ""
echo "=========================================="
echo "  Configuring IPsec secrets (/etc/ipsec.secrets)..."
echo "=========================================="

cat > /etc/ipsec.secrets << EOF
$PUBLIC_IP %any : PSK "$IPSEC_PSK"
EOF

chmod 600 /etc/ipsec.secrets
ok "/etc/ipsec.secrets written (chmod 600)"

echo ""
echo "=========================================="
echo "  Configuring xl2tpd (/etc/xl2tpd/xl2tpd.conf)..."
echo "=========================================="

mkdir -p /etc/xl2tpd
cat > /etc/xl2tpd/xl2tpd.conf << EOF
[global]
port = 1701
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
ok "/etc/xl2tpd/xl2tpd.conf written"

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
echo "  Configuring accel-ppp (SSTP on port 943)..."
echo "=========================================="

mkdir -p /etc/accel-ppp /var/log/accel-ppp
cat > /etc/accel-ppp.conf << EOF
[modules]
log_file
sstp
auth
chap-msv2
ippool

[core]
log-error=/var/log/accel-ppp/core.log
thread-count=4

[common]
single-session=replace
sid-case=upper
sid-source=seq

[log]
log-file=/var/log/accel-ppp/accel-ppp.log
log-emerg=/var/log/accel-ppp/emerg.log
log-fail-file=/var/log/accel-ppp/auth-fail.log
copy=3
color=1
default=error

[ppp]
verbose=1
min-mtu=1280
mtu=1410
mru=1410
ipv4=require
ipv6=deny
mtu-disc=yes
lcp-echo-failure=4
lcp-echo-interval=30

[dns]
dns1=$DNS1
dns2=$DNS2

[sstp]
host=0.0.0.0
port=943
verbose=1

[ip-pool]
gw-ip-address=10.255.1.1
$SSTP_START-$SSTP_END

[chap-msv2]

[auth]
any-login=0
noauth=0
EOF
ok "/etc/accel-ppp.conf written"
else
echo ""
info "SSTP skipped — accel-ppp not installed."
fi

echo ""
echo "=========================================="
echo "  Configuring /etc/ppp/chap-secrets template..."
echo "=========================================="

cat > /etc/ppp/chap-secrets << 'EOF'
# Secrets for authentication using CHAP
# Format:
# client    server    secret    IP address
# Example:
# vpnuser1  *         MySecurePass123  *
# vpnuser2  *         AnotherPass456   10.255.0.150
#
# client    - PPP username (router L2TP/SSTP login)
# server    - server name (use "*" for any)
# secret    - PPP password
# IP address - static IP for this user, or "*" to assign from pool
EOF

chmod 600 /etc/ppp/chap-secrets
ok "/etc/ppp/chap-secrets written (chmod 600)"

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
echo "  Configuring iptables NAT for 10.255.0.0/16..."
echo "=========================================="

iptables -t nat -F 2>/dev/null || true
iptables -F 2>/dev/null || true

iptables -t nat -A POSTROUTING -s 10.255.0.0/16 -o "$MAIN_IF" -j MASQUERADE

iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -s 10.255.0.0/16 -j ACCEPT
iptables -A FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
iptables -A FORWARD -j REJECT

ok "iptables NAT + forwarding rules applied"

echo ""
echo "=========================================="
echo "  Saving iptables rules (persistent)..."
echo "=========================================="

mkdir -p /etc/iptables
if command -v iptables-save >/dev/null 2>&1; then
    iptables-save > /etc/iptables/rules.v4 2>/dev/null && echo "iptables saved to /etc/iptables/rules.v4" || true
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

echo ""
echo "=========================================="
echo -e "  ${GREEN}Installation complete!${NC}"
echo "=========================================="
echo ""
echo "Public IP:        $PUBLIC_IP"
echo "IPsec PSK:        $IPSEC_PSK"
echo "L2TP port:        1701 (UDP) + 500/4500 (UDP for IKE/NAT-T)"
echo "L2TP PPP range:   $PPP_START - $PPP_END"
echo "DNS servers:      $DNS1, $DNS2"
echo "Main interface:   $MAIN_IF"
if [ "$SSTP_OK" = "yes" ]; then
echo "SSTP port:        943 (TCP)"
echo "SSTP PPP range:   $SSTP_START - $SSTP_END"
else
echo "SSTP:             SKIPPED (accel-ppp not installed)"
fi
echo ""
echo "Users are managed in /etc/ppp/chap-secrets"
echo "Format:  username  *  password  *"
echo ""
echo "To sync users from the web admin panel:"
echo "  1) Create routers with L2TP credentials in UI"
echo "  2) Run POST /api/vpn/sync or click Sync button in dashboard"
echo ""
echo "To check L2TP logs:"
echo "  journalctl -u xl2tpd -f"
echo "  tail -f /var/log/syslog | grep -E 'xl2tpd|pppd|ipsec'"
echo ""
