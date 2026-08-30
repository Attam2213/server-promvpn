#!/bin/bash
set -e

echo "=========================================="
echo "  VPN Manager - Systemd Service Installer"
echo "=========================================="
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: Run this script as root (sudo bash start_manager.sh)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Backend directory: $BACKEND_DIR"
echo ""

PYTHON_BIN=$(command -v python3 || command -v python || true)
if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: Python 3 is not installed"
    exit 1
fi
echo "Python binary: $PYTHON_BIN"

UVICORN_BIN=$(command -v uvicorn || true)
if [ -z "$UVICORN_BIN" ]; then
    if [ -f "$BACKEND_DIR/venv/bin/uvicorn" ]; then
        UVICORN_BIN="$BACKEND_DIR/venv/bin/uvicorn"
    else
        echo "WARNING: uvicorn not found globally, installing via pip..."
        $PYTHON_BIN -m pip install -r "$BACKEND_DIR/requirements.txt"
        UVICORN_BIN="$($PYTHON_BIN -c 'import uvicorn, os; print(os.path.join(os.path.dirname(uvicorn.__file__), "..", "..", "bin", "uvicorn"))' 2>/dev/null || command -v uvicorn || echo "$PYTHON_BIN -m uvicorn")"
    fi
fi
echo "Uvicorn: $UVICORN_BIN"
echo ""

read -p "Service user to run as [root]: " RUN_USER
RUN_USER=${RUN_USER:-root}

read -p "Listen host [0.0.0.0]: " LISTEN_HOST
LISTEN_HOST=${LISTEN_HOST:-0.0.0.0}

read -p "Listen port [8000]: " LISTEN_PORT
LISTEN_PORT=${LISTEN_PORT:-8000}

echo ""
echo "Creating systemd unit at /etc/systemd/system/vpn-manager.service..."

cat > /etc/systemd/system/vpn-manager.service << EOF
[Unit]
Description=VPN VDS Manager API Service
After=network.target xl2tpd.service accel-ppp.service ipsec.service
Wants=network.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$BACKEND_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$UVICORN_BIN app.main:app --host $LISTEN_HOST --port $LISTEN_PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

chmod 644 /etc/systemd/system/vpn-manager.service

echo ""
echo "Reloading systemd daemon..."
systemctl daemon-reload

echo "Enabling vpn-manager service on boot..."
systemctl enable vpn-manager

echo "Starting vpn-manager service..."
systemctl restart vpn-manager

sleep 2

echo ""
echo "=========================================="
echo "  Service status:"
echo "=========================================="
systemctl status vpn-manager --no-pager -l | head -20

echo ""
echo "=========================================="
echo "  Useful commands:"
echo "=========================================="
echo "  Check logs:    journalctl -u vpn-manager -f"
echo "  Status:        systemctl status vpn-manager"
echo "  Restart:       systemctl restart vpn-manager"
echo "  Stop:          systemctl stop vpn-manager"
echo "  Disable boot:  systemctl disable vpn-manager"
echo ""
echo "API should be available at http://$PUBLIC_IP_OR_LOCALHOST:$LISTEN_PORT"
echo "Health check:    http://localhost:$LISTEN_PORT/api/health"
echo ""
