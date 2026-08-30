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

if [[ $EUID -ne 0 ]]; then
    err "Запусти скрипт с sudo или как root."
    echo "  sudo bash $0"
    exit 1
fi

cd "$(dirname "$(readlink -f "$0")")"
PROJECT_ROOT="$(pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"

REPO_URL="https://github.com/Attam2213/server-promvpn.git"
APP_SERVICE_NAME="vpn-manager"
APP_PORT="${APP_PORT:-8000}"
APP_USER="${APP_USER:-root}"
FRONTEND_DIR="${FRONTEND_DIR:-$PROJECT_ROOT/frontend}"

echo ""
echo "========================================================="
echo "  VPN VDS Manager — INSTALL"
echo "  Repo   : $REPO_URL"
echo "  PWD    : $PROJECT_ROOT"
echo "  User   : $APP_USER  (systemd service)"
echo "  Port   : $APP_PORT"
echo "========================================================="
echo ""

info "1/7. Обновляем индексы пакетов и ставим системные зависимости..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq || true
apt-get install -y -qq --no-install-recommends \
    git curl ca-certificates wget tzdata locales \
    python3 python3-venv python3-pip python3-dev \
    build-essential libffi-dev libssl-dev 2>&1 | tail -3 || true
ok "Системные пакеты установлены."

if [[ ! -f "$PROJECT_ROOT/backend/requirements.txt" ]]; then
    info "2/7. Репозиторий ещё не клонирован — клонируем $REPO_URL..."
    cd /tmp
    if [[ -d server-promvpn ]]; then rm -rf server-promvpn; fi
    git clone --depth 1 "$REPO_URL" server-promvpn || true
    if [[ -d server-promvpn/vpn-manager ]]; then
        mkdir -p "$(dirname "$PROJECT_ROOT")"
        rm -rf "$PROJECT_ROOT"
        mv server-promvpn "$(dirname "$PROJECT_ROOT")/.." 2>/dev/null || true
        if [[ -d "/tmp/server-promvpn/vpn-manager" ]]; then
            TMP_PARENT="/tmp/server-promvpn"
            TARGET_PARENT="$(dirname "$PROJECT_ROOT")"
            if [[ ! -d "$TARGET_PARENT/server-promvpn/.git" ]]; then
                mkdir -p "$TARGET_PARENT"
                rm -rf "$TARGET_PARENT/server-promvpn"
                mv /tmp/server-promvpn "$TARGET_PARENT/server-promvpn" || cp -a /tmp/server-promvpn "$TARGET_PARENT/server-promvpn"
            fi
            if [[ -d "$TARGET_PARENT/server-promvpn/vpn-manager" ]]; then
                if [[ ! -e "$PROJECT_ROOT" ]]; then
                    ln -s "$TARGET_PARENT/server-promvpn/vpn-manager" "$PROJECT_ROOT" 2>/dev/null || true
                fi
            fi
        fi
        rm -rf /tmp/server-promvpn 2>/dev/null || true
    fi
    if [[ ! -f "$PROJECT_ROOT/backend/requirements.txt" ]]; then
        warn "Не удалось клонировать — требуется ручная установка:"
        echo "    cd /opt && git clone $REPO_URL server-promvpn"
        echo "    ln -s /opt/server-promvpn/vpn-manager $PROJECT_ROOT"
    fi
else
    info "2/7. Проект уже найден локально — шаг с клонированием пропущен."
    if [[ ! -d "$PROJECT_ROOT/.git" ]] && [[ -d "$PROJECT_ROOT/../.git" ]] && [[ "$(basename "$(dirname "$PROJECT_ROOT")")" == "server-promvpn" ]]; then
        ok "Найден родительский git-репозиторий — update.sh будет работать через родительский .git"
    fi
fi

info "3/7. Создаём Python venv и ставим зависимости..."
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR" || true
fi
"$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel --quiet || true
"$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt" --quiet || true
if "$VENV_DIR/bin/python" -c "import fastapi, uvicorn, sqlalchemy" 2>/dev/null; then
    ok "Python зависимости установлены в $VENV_DIR"
else
    err "Критические пакеты не установились. Проверь pip: $VENV_DIR/bin/pip install -r $BACKEND_DIR/requirements.txt"
fi

info "4/7. Устанавливаем L2TP + SSTP VPN сервер (xl2tpd + libreswan + accel-ppp)..."
VPN_INSTALL="$BACKEND_DIR/scripts/install_vpn.sh"
if [[ -f "$VPN_INSTALL" ]]; then
    chmod +x "$VPN_INSTALL"
    bash "$VPN_INSTALL" || warn "install_vpn.sh завершился с ошибками — смотри лог выше, поправишь руками потом."
else
    warn "Не найден $VPN_INSTALL — шаг с VPN пропущен."
fi

info "5/7. Создаём systemd юнит $APP_SERVICE_NAME.service..."
SERVICE_FILE="/etc/systemd/system/${APP_SERVICE_NAME}.service"
cat > "$SERVICE_FILE" <<SYSTEMD
[Unit]
Description=VPN VDS Manager (FastAPI)
After=network.target xl2tpd.service accel-ppp.service ipsec.service

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$BACKEND_DIR
Environment="PATH=$VENV_DIR/bin"
Environment="PYTHONUNBUFFERED=1"
Environment="FRONTEND_DIR=$FRONTEND_DIR"
ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host 0.0.0.0 --port $APP_PORT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SYSTEMD
ok "Юнит записан: $SERVICE_FILE"

systemctl daemon-reload || true
systemctl enable "$APP_SERVICE_NAME" || true
systemctl restart "$APP_SERVICE_NAME" || true
sleep 3
ok "Сервис $APP_SERVICE_NAME запущен и добавлен в автозагрузку."

info "6/7. Синхронизируем учётки БД → chap-secrets..."
SYNC_OUTPUT=$("$VENV_DIR/bin/python" -c "
import sys; sys.path.insert(0, '$BACKEND_DIR')
from app.database import SessionLocal
from app.services.vpn_manager import VpnManager
m = VpnManager()
print(m.sync_routers_to_vpn(SessionLocal()))
" 2>&1 || true)
ok "Результат sync_routers_to_vpn: $SYNC_OUTPUT"

info "7/7. Проверка healthcheck..."
sleep 2
HEALTH=$(curl -s --max-time 5 "http://127.0.0.1:${APP_PORT}/api/health" || echo "")
if echo "$HEALTH" | grep -q "ok"; then
    ok "API отвечает: /api/health -> $HEALTH"
else
    warn "Healthcheck не прошёл. Смотри логи: journalctl -u $APP_SERVICE_NAME -n 50 --no-pager"
    systemctl --no-pager status "$APP_SERVICE_NAME" --lines=10 || true
fi

PUB_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "<VDS_IP>")
echo ""
echo "========================================================="
echo -e "  ${GREEN}УСТАНОВКА ЗАВЕРШЕНА${NC}"
echo ""
echo "  Панель         : http://${PUB_IP}:${APP_PORT}/"
echo "  Swagger API    : http://${PUB_IP}:${APP_PORT}/docs"
echo "  Логин по умолч.  : admin / admin (НЕ ЗАБУДЬ СМЕНИТЬ!)"
echo ""
echo "  Журналы:"
echo "    journalctl -u $APP_SERVICE_NAME -f"
echo "    systemctl status $APP_SERVICE_NAME"
echo ""
echo "  Команды управления:"
echo "    bash $PROJECT_ROOT/update.sh        # подтянуть обновления с GitHub"
echo "    systemctl restart $APP_SERVICE_NAME # перезапуск менеджера"
echo "    systemctl restart xl2tpd 2>/dev/null; systemctl restart ipsec 2>/dev/null || systemctl restart libreswan 2>/dev/null || true"
echo "========================================================="
echo ""
