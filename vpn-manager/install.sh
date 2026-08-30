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
ADMIN_PASSWORD_ENV="${ADMIN_PASSWORD:-}"
PASSLIB_SCHEME_ENV="${PASSLIB_SCHEME:-sha256_crypt}"

echo ""
echo "========================================================="
echo "  VPN VDS Manager — INSTALL"
echo "  Repo   : $REPO_URL"
echo "  PWD    : $PROJECT_ROOT"
echo "  User   : $APP_USER  (systemd service)"
echo "  Port   : $APP_PORT"
echo "========================================================="
echo ""

if [[ -z "$MGMT_IP" ]] || [[ -z "$VPN_PUBLIC_IP" ]]; then
    echo "Поддержка 2-х публичных IP: MGMT (панель + SSH) и VPN_PUBLIC_IP (L2TP/IPsec туннели)."
    echo "Если у тебя только 1 IP — вводи один и тот же адрес дважды."
    echo ""
fi
if [[ -z "$MGMT_IP" ]]; then
    DEF_MGMT=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || true)
    read -p "  MGMT_IP (для панели :8000 + SSH :22) [${DEF_MGMT:-<auto>}]: " MGMT_IP
    MGMT_IP=${MGMT_IP:-$DEF_MGMT}
    if [[ -z "$MGMT_IP" ]]; then
        echo "Введите MGMT_IP вручную или повторите запуск с ENV: MGMT_IP=X.X.X.X VPN_PUBLIC_IP=Y.Y.Y.Y sudo bash install.sh"
        exit 1
    fi
fi
if [[ -z "$VPN_PUBLIC_IP" ]]; then
    read -p "  VPN_PUBLIC_IP (для L2TP/IPsec туннелей с MikroTik) [${MGMT_IP}]: " VPN_PUBLIC_IP
    VPN_PUBLIC_IP=${VPN_PUBLIC_IP:-$MGMT_IP}
fi
export MGMT_IP="$MGMT_IP"
export VPN_PUBLIC_IP="$VPN_PUBLIC_IP"

APP_LISTEN_IP="${APP_LISTEN_IP:-${MGMT_IP}}"
echo "MGMT_IP      = $MGMT_IP (FastAPI :$APP_PORT будет слушать ЗДЕСЬ)"
echo "VPN_PUBLIC_IP = $VPN_PUBLIC_IP (тут только L2TP/IPsec :500/:1701/:4500)"
echo "APP_LISTEN_IP = $APP_LISTEN_IP (хост --host для uvicorn)"
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
    export MGMT_IP="$MGMT_IP"
    export VPN_PUBLIC_IP="$VPN_PUBLIC_IP"
    bash "$VPN_INSTALL" || warn "install_vpn.sh завершился с ошибками — смотри лог выше, поправишь руками потом."
else
    warn "Не найден $VPN_INSTALL — шаг с VPN пропущен."
fi

info "5/7. Создаём systemd юнит $APP_SERVICE_NAME.service..."
SERVICE_FILE="/etc/systemd/system/${APP_SERVICE_NAME}.service"
{
echo "[Unit]"
echo "Description=VPN VDS Manager (FastAPI)"
echo "After=network.target xl2tpd.service accel-ppp.service ipsec.service"
echo ""
echo "[Service]"
echo "Type=simple"
echo "User=$APP_USER"
echo "WorkingDirectory=$BACKEND_DIR"
echo "Environment=\"PATH=$VENV_DIR/bin\""
echo "Environment=\"PYTHONUNBUFFERED=1\""
echo "Environment=\"FRONTEND_DIR=$FRONTEND_DIR\""
echo "Environment=\"PASSLIB_SCHEME=$PASSLIB_SCHEME_ENV\""
if [[ -n "$MGMT_IP" ]]; then
    echo "Environment=\"MGMT_IP=$MGMT_IP\""
fi
if [[ -n "$VPN_PUBLIC_IP" ]]; then
    echo "Environment=\"VPN_PUBLIC_IP=$VPN_PUBLIC_IP\""
fi
if [[ -n "$ADMIN_PASSWORD_ENV" ]]; then
    echo "Environment=\"ADMIN_PASSWORD=$ADMIN_PASSWORD_ENV\""
fi
echo "ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host $APP_LISTEN_IP --port $APP_PORT"
echo "Restart=always"
echo "RestartSec=5"
echo "StandardOutput=journal"
echo "StandardError=journal"
echo ""
echo "[Install]"
echo "WantedBy=multi-user.target"
} > "$SERVICE_FILE"
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
