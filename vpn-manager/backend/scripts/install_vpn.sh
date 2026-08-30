#!/bin/bash
set -e

echo "=========================================="
echo "  L2TP + SSTP VPN Server Installer"
echo "  for Ubuntu / Debian VDS"
echo "=========================================="
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run this script as root (sudo bash install_vpn.sh)"
    exit 1
fi

read -p "Enter public IP of this VDS: " PUBLIC_IP
if [ -z "$PUBLIC_IP" ]; then
    echo "ERROR: Public IP is required"
    exit 1
fi

read -p "Enter IPsec PSK password (shared secret): " IPSEC_PSK
if [ -z "$IPSEC_PSK" ]; then
    echo "ERROR: IPsec PSK is required"
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

read -p "Enter SSTP IP range start [10.255.1.100]: " SSTP_START
SSTP_START=${SSTP_START:-10.255.1.100}
read -p "Enter SSTP IP range end [10.255.1.200]: " SSTP_END
SSTP_END=${SSTP_END:-10.255.1.200}

echo ""
echo "=========================================="
echo "  Installing packages..."
echo "=========================================="

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y xl2tpd libreswan ppp iptables-persistent accel-ppp

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
EOF
sysctl -p /etc/sysctl.d/99-vpn-forward.conf

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

echo ""
echo "=========================================="
echo "  Configuring IPsec secrets (/etc/ipsec.secrets)..."
echo "=========================================="

cat > /etc/ipsec.secrets << EOF
$PUBLIC_IP %any : PSK "$IPSEC_PSK"
EOF

chmod 600 /etc/ipsec.secrets

echo ""
echo "=========================================="
echo "  Configuring xl2tpd (/etc/xl2tpd/xl2tpd.conf)..."
echo "=========================================="

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
debug
name l2tpd
proxyarp
lcp-echo-failure 4
lcp-echo-interval 30
mtu 1410
mru 1410
noipx
EOF

echo ""
echo "=========================================="
echo "  Configuring accel-ppp (SSTP on port 943)..."
echo "=========================================="

mkdir -p /etc/accel-ppp
cat > /etc/accel-ppp.conf << EOF
[modules]
log_file
pptp
l2tp
sstp
pppoe
auth
chap-msv2
radius
ippool
shaper
net-snmp

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
log-debug=/var/log/accel-ppp/debug.log
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

echo ""
echo "=========================================="
echo "  Detecting main network interface..."
echo "=========================================="

MAIN_IF=$(ip -4 route ls | grep default | grep -Po '(?<=dev )(\S+)' | head -1)
if [ -z "$MAIN_IF" ]; then
    MAIN_IF=$(ls /sys/class/net | grep -E '^(eth|ens|enp|wlan)' | head -1)
fi
echo "Using main interface: $MAIN_IF"

echo ""
echo "=========================================="
echo "  Configuring iptables NAT for 10.255.0.0/16..."
echo "=========================================="

iptables -t nat -F
iptables -F

iptables -t nat -A POSTROUTING -s 10.255.0.0/16 -o $MAIN_IF -j MASQUERADE

iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -s 10.255.0.0/16 -j ACCEPT
iptables -A FORWARD -j REJECT

echo ""
echo "=========================================="
echo "  Saving iptables rules (persistent)..."
echo "=========================================="

if command -v iptables-save >/dev/null 2>&1; then
    iptables-save > /etc/iptables/rules.v4
    echo "iptables saved to /etc/iptables/rules.v4"
fi

echo ""
echo "=========================================="
echo "  Enabling and starting services..."
echo "=========================================="

systemctl enable ipsec 2>/dev/null || systemctl enable libreswan 2>/dev/null || true
systemctl enable xl2tpd 2>/dev/null || true
systemctl enable accel-ppp 2>/dev/null || true

systemctl restart ipsec 2>/dev/null || systemctl restart libreswan 2>/dev/null || true
systemctl restart xl2tpd 2>/dev/null || true
systemctl restart accel-ppp 2>/dev/null || true

sleep 2

echo ""
echo "=========================================="
echo "  Service status check:"
echo "=========================================="

for svc in ipsec libreswan xl2tpd accel-ppp; do
    if systemctl is-active --quiet $svc 2>/dev/null; then
        echo "  [OK]   $svc is running"
    else
        echo "  [WARN] $svc is NOT running (may be named differently on this distro)"
    fi
done

echo ""
echo "=========================================="
echo "  Installation complete!"
echo "=========================================="
echo ""
echo "Public IP:        $PUBLIC_IP"
echo "IPsec PSK:        $IPSEC_PSK"
echo "L2TP PPP range:   $PPP_START - $PPP_END"
echo "SSTP port:        943"
echo "SSTP PPP range:   $SSTP_START - $SSTP_END"
echo "DNS servers:      $DNS1, $DNS2"
echo "Main interface:   $MAIN_IF"
echo ""
echo "Users are managed in /etc/ppp/chap-secrets"
echo "Format:  username  *  password  *"
echo ""
echo "To sync users from the web admin panel, use POST /api/vpn/sync"
echo ""
