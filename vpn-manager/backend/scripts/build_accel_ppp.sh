#!/bin/bash
#
# accel-ppp (SSTP/L2TP/PPTP server) — source build installer
# ---------------------------------------------------------
# Compiles from GitHub accel-ppp/accel-ppp (modern maintained fork)
# Dependencies: build-essential cmake git linux-headers libssl-dev libpcre3-dev libev-dev
# Env overrides:
#   VPN_PUBLIC_IP  — bind SSTP/TCP and IP-helper socket to this IP (default 0.0.0.0)
#   ACCEL_GIT_URL  — git URL (default github)
#   ACCEL_GIT_REF  — branch/tag/commit (default master)
#

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${BOLD}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[FAIL]${NC}  $1" >&2; }

if [ "$(id -u)" -ne 0 ]; then
    err "Run as root: sudo bash build_accel_ppp.sh"
    exit 1
fi

: "${VPN_PUBLIC_IP:=0.0.0.0}"
: "${ACCEL_GIT_URL:=https://github.com/accel-ppp/accel-ppp.git}"
: "${ACCEL_GIT_REF:=1.12.0}"
: "${BUILD_DIR:=/tmp/accel-ppp-build}"
: "${SRC_DIR:=/usr/local/src/accel-ppp}"

DNS1="${DNS1:-8.8.8.8}"
DNS2="${DNS2:-1.1.1.1}"
PPP_START="${PPP_START:-10.255.1.100}"
PPP_END="${PPP_END:-10.255.1.200}"
SSTP_PORT="${SSTP_PORT:-443}"
SSTP_LOCAL_IP="${SSTP_LOCAL_IP:-10.255.1.1}"

echo "=========================================="
echo "  accel-ppp SSTP source build installer"
echo "  repo: $ACCEL_GIT_URL ($ACCEL_GIT_REF)"
echo "  bind VPN_IP: $VPN_PUBLIC_IP"
echo "  SSTP TCP port: $SSTP_PORT"
echo "=========================================="

export DEBIAN_FRONTEND=noninteractive

info "Installing build dependencies..."
apt-get update -y -qq || true
# accel-ppp upstream cmake checks first for libpcre (libpcre2-8) then falls back to pcre3.
# Install BOTH to avoid "Required libpcre not found."
apt-get install -y -qq --no-install-recommends \
  build-essential cmake git ca-certificates pkg-config \
  libssl-dev libev-dev \
  libpcre2-dev libpcre3-dev libpcre++-dev \
  linux-headers-$(uname -r) 2>&1 | tail -5 || \
  apt-get install -y -qq --no-install-recommends linux-headers-generic libpcre2-dev libpcre3-dev libpcre++-dev 2>&1 | tail -3 || true
# Sanity check — at least one pcre must be present, else hard fail
if ! ldconfig -p | grep -Eq 'libpcre(2-8|3)?\.so' && \
   ! ( dpkg -l libpcre2-dev libpcre3-dev 2>/dev/null | grep -q '^ii' ); then
    err "Could not install libpcre2-dev / libpcre3-dev — required for accel-ppp regex module."
    exit 3
fi
ok "Build deps installed"

info "Cloning accel-ppp sources..."
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
if [ -d "$SRC_DIR/.git" ]; then
    info "Updating existing source in $SRC_DIR"
    (cd "$SRC_DIR" && git fetch --tags --depth 1 2>/dev/null || git pull --ff-only 2>/dev/null || true)
else
    mkdir -p "$(dirname "$SRC_DIR")"
    git clone --depth 1 --branch "$ACCEL_GIT_REF" "$ACCEL_GIT_URL" "$SRC_DIR" 2>&1 | tail -3
fi
[ -d "$SRC_DIR/accel-pppd" ] || {
    err "accel-ppp source checkout FAIL: missing accel-pppd dir after clone"
    exit 2
}
ok "Sources ready"

info "CMake configure..."
(
  cd "$BUILD_DIR" && rm -f CMakeCache.txt
  cmake "$SRC_DIR" \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_DRIVER=FALSE \
    -DSHAPER=FALSE \
    -DNETSNMP=FALSE \
    -DRADIUS=FALSE \
    -DMEMDEBUG=FALSE \
    -DSSTP=TRUE \
    -DPPTP=FALSE \
    -DL2TP=FALSE \
    -DIPOE=FALSE \
    -DPPPOE=FALSE \
    -DLOG_FILE=TRUE \
    -DLOG_TCP=FALSE \
    -DLOG_SYSLOG=TRUE 2>&1 | tail -40
)
if [ ! -f "$BUILD_DIR/Makefile" ] && [ ! -f "$BUILD_DIR/build.ninja" ]; then
    err "cmake configure FAILED — see tail above (most often missing libpcre/libssl/libev)."
    err "Install manually: apt install -y libpcre2-dev libpcre3-dev libssl-dev libev-dev, then retry."
    exit 4
fi
ok "cmake configure done"

BUILD_JOBS="$(nproc 2>/dev/null || echo 2)"
info "Compiling with -j$BUILD_JOBS (takes 2-10 minutes)..."
( cd "$BUILD_DIR" && make -j"$BUILD_JOBS" 2>&1 | tail -50 )
if [ ! -x "$BUILD_DIR/accel-pppd/accel-pppd" ] && \
   [ ! -x "$BUILD_DIR/accel-pppd" ]; then
    err "make compile FAILED — no accel-pppd binary produced. Check build output above."
    exit 5
fi
ok "Compiled"

info "Installing binaries to /usr..."
( cd "$BUILD_DIR" && make install 2>&1 | tail -20 )

# accel-cmd CLI usually installs to /usr/bin — ensure PATH symlink
[ -x /usr/sbin/accel-pppd ] || ln -sf /usr/bin/accel-pppd /usr/sbin/accel-pppd 2>/dev/null || true
[ -x /usr/sbin/accel-cmd ]   || ln -sf /usr/bin/accel-cmd   /usr/sbin/accel-cmd   2>/dev/null || true
ldconfig || true
ok "accel-ppp installed. Binaries: $(command -v accel-pppd || echo NOTFOUND) / $(command -v accel-cmd || echo NOTFOUND)"

# Ensure PPP/GRE kernel modules are loaded (accel-ppp SIGFPE without them)
info "Loading PPP/GRE kernel modules..."
modprobe -a ppp_generic ppp_async ppp_mppe ppp_deflate ppp_bsdcomp slhc ip_gre nf_conntrack_pptp nf_conntrack_proto_gre 2>/dev/null || true
for m in iptable_nat xt_addrtype xt_comment xt_conntrack xt_multiport xt_tcpudp xt_owner nf_nat nf_conntrack; do
    modprobe "$m" 2>/dev/null || true
done
ok "Kernel PPP modules loaded (accel-ppp will not SIGFPE now)"

info "Creating config directories + chap-secrets..."
mkdir -p /etc/accel-ppp/conf /var/log/accel-ppp /var/run/accel-ppp
touch /etc/accel-ppp/conf/chap-secrets
chmod 600 /etc/accel-ppp/conf/chap-secrets

info "Writing /etc/accel-ppp/accel-ppp.conf (SSTP bind=0.0.0.0:$SSTP_PORT)..."
# NOTE: we use host=0.0.0.0 (not specific VPN_PUBLIC_IP) to avoid bind failures with
# policy routing / netfilter marks. The MGMT:443 has no user-facing service anyway,
# and iptables rules already restrict incoming 443 to -d $VPN_PUBLIC_IP only.
cat > /etc/accel-ppp/accel-ppp.conf << EOF
[modules]
log_file
log_syslog
sstp
auth_pap
auth_mschap_v2
chap-secrets
ippool
connlimit

[core]
log-error=/var/log/accel-ppp/core.log
thread-count=1
die-on-modload-error=no
# Avoid SIGFPE si_code=FPE_INTDIV (division by zero on max_sessions=0, driver=NULL)
max-sessions=200
max-async-sessions=200
max-sync-sessions=200

[common]
single-session=replace
sid-case=upper
sid-source=seq

[connlimit]
limit=0
timeout=60
burst=3

[log]
log-file=/var/log/accel-ppp/accel-ppp.log
log-emerg=/var/log/accel-ppp/emerg.log
log-fail-file=/var/log/accel-ppp/auth-fail.log
log-syslog=daemon
syslog-facility=daemon
syslog-level=notice
copy=3
default=notice

[ppp]
verbose=0
min-mtu=1280
mtu=1400
mru=1400
ipv4=require
ipv6=deny
mtu-disc=yes
lcp-echo-failure=4
lcp-echo-interval=30
check-ip=0
unit-cache=100

[dns]
dns1=$DNS1
dns2=$DNS2

[sstp]
host=0.0.0.0
port=$SSTP_PORT
verbose=0
certificate=/etc/accel-ppp/certs/sstp.crt
private-key=/etc/accel-ppp/certs/sstp.key

[ip-pool]
gw-ip-address=$SSTP_LOCAL_IP
$PPP_START-$PPP_END

[mschap]

[auth]
any-login=0
noauth=0
# /etc/accel-ppp/conf/chap-secrets is in standard tab-separated chap-secrets format
# This path matches backend VpnManager.ACCEL_PPP_SECRETS_PATH
secrets=/etc/accel-ppp/conf/chap-secrets
EOF
ok "accel-ppp.conf written"

info "Generating self-signed SSTP certificate (valid 10 years)..."
mkdir -p /etc/accel-ppp/certs
CERT_CN="${CERT_CN:-$VPN_PUBLIC_IP}"
if [ ! -f /etc/accel-ppp/certs/sstp.key ] || [ ! -f /etc/accel-ppp/certs/sstp.crt ]; then
    (
      cd /etc/accel-ppp/certs
      openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout sstp.key \
        -out sstp.crt \
        -days 3650 \
        -subj "/C=RU/ST=Moscow/L=Moscow/O=PromVpn/OU=SSTP/CN=$CERT_CN" 2>/dev/null
      cp -f sstp.crt ca.crt
      chmod 600 sstp.key
      chmod 644 sstp.crt ca.crt
    )
    ok "Self-signed cert generated /etc/accel-ppp/certs/sstp.crt (CN=$CERT_CN)"
else
    info "Using existing certificate at /etc/accel-ppp/certs/"
fi

info "Installing systemd unit /etc/systemd/system/accel-ppp.service..."
# Use Type=simple + RuntimeDirectory + NO CapabilityBoundingSet (avoid permission denied on PID file / FPE)
# We intentionally skip hardening caps because accel-ppp v1.12 needs setuid/setgid + dac override for ppp
cat > /etc/systemd/system/accel-ppp.service << 'EOF'
[Unit]
Description=accel-ppp SSTP VPN server (accel-pppd)
After=network-online.target syslog.target remote-fs.target nss-lookup.target
Wants=network-online.target
Documentation=https://accel-ppp.readthedocs.io/

[Service]
Type=forking
User=root
Group=root
Environment=LC_ALL=C LANG=C
PIDFile=/run/accel-ppp/accel-ppp.pid
RuntimeDirectory=accel-ppp
RuntimeDirectoryMode=0755
RuntimeDirectoryPreserve=yes
# Ensure directories exist before start
ExecStartPre=-/bin/mkdir -p /run/accel-ppp /var/log/accel-ppp /etc/accel-ppp/conf
ExecStartPre=-/bin/chmod 0755 /run/accel-ppp /var/log/accel-ppp
ExecStartPre=-/sbin/modprobe -a ppp_generic ppp_async ppp_mppe ip_gre 2>/dev/null || true
ExecStart=/usr/sbin/accel-pppd -d -c /etc/accel-ppp/accel-ppp.conf -p /run/accel-ppp/accel-ppp.pid
ExecReload=/bin/kill -HUP $MAINPID
ExecStop=/bin/kill -TERM $MAINPID
KillSignal=SIGTERM
TimeoutStopSec=15
FinalKillSignal=SIGKILL
KillMode=mixed
Restart=on-abnormal
RestartSec=2
RestartForceExitStatus=SIGPIPE FPE
StartLimitBurst=5
StartLimitIntervalSec=60
LimitNOFILE=16384
LimitNPROC=infinity

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl reset-failed accel-ppp 2>/dev/null || true
systemctl enable accel-ppp 2>/dev/null || true
ok "systemd unit accel-ppp.service installed + enabled"

if command -v ss >/dev/null 2>&1 && ss -tln | grep -qE "[:.]443\s"; then
    warn "TCP port 443 already LISTENING on host — accel-ppp might fail to bind SSTP socket. Check netstat/ss."
fi

info "Restarting accel-ppp..."
systemctl reset-failed accel-ppp 2>/dev/null || true
rm -f /run/accel-ppp/accel-ppp.pid /var/run/accel-ppp/accel-ppp.pid
sleep 0.5
systemctl restart accel-ppp 2>/dev/null || {
    warn "accel-ppp start failed. Check: journalctl -u accel-ppp -n 60  ; or manual: /usr/sbin/accel-pppd -d -c /etc/accel-ppp/accel-ppp.conf"
}
sleep 2

if systemctl is-active --quiet accel-ppp 2>/dev/null; then
    ok "✅ accel-ppp (SSTP) is running!"
    if command -v accel-cmd >/dev/null 2>&1; then
        info "accel-cmd CLI: run 'accel-cmd show sessions' to view active SSTP sessions"
    fi
else
    warn "accel-ppp did not start — review: journalctl -u accel-ppp -n 60"
fi

echo ""
echo "=========================================="
echo -e "  ${GREEN}SSTP accel-ppp source build DONE${NC}"
echo "=========================================="
echo ""
echo "  Config      : /etc/accel-ppp/accel-ppp.conf"
echo "  Secrets file: /etc/accel-ppp/conf/chap-secrets (synced by UI VPN Sync)"
echo "  Cert        : /etc/accel-ppp/certs/sstp.crt  (self-signed, copy to Windows/MikroTik trusted store if needed)"
echo "  Key         : /etc/accel-ppp/certs/sstp.key"
echo "  Systemd     : systemctl restart accel-ppp  /  journalctl -u accel-ppp -f"
echo "  Sessions    : accel-cmd show sessions"
echo ""
echo "  MikroTik SSTP client: /interface sstp-client add connect-to=$VPN_PUBLIC_IP user=<router> password=<pass> certificate=add-to-store"
echo "  (self-signed cert: disable TLS verify or import sstp.crt on MikroTik)"
