#!/bin/bash
set -e

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${BOLD}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[ OK ]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
err()   { echo -e "${RED}[FAIL]${NC}  $1" >&2; }

cd "$(dirname "$(readlink -f "$0")")"
PROJECT_ROOT="$(pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"
SERVICE_NAME="${SERVICE_NAME:-vpn-manager}"

echo ""
echo "========================================================="
echo "  VPN VDS Manager — UPDATE (git pull + restart)"
echo "  PWD    : $PROJECT_ROOT"
echo "========================================================="
echo ""

if [[ ! -d ".git" ]]; then
    err "Папка $PROJECT_ROOT не является git репозиторием."
    echo "  Клонируй репу вручную:"
    echo "    cd /opt && git clone https://github.com/Attam2213/server-promvpn.git"
    echo "    ln -s /opt/server-promvpn/vpn-manager /opt/vpn-manager"
    exit 1
fi

info "1/4. Сохраняем локальные правки (если есть)..."
BEFORE=$(git rev-parse HEAD || echo "unknown")
STASH_MSG=""
if [[ -n "$(git status --porcelain)" ]]; then
    warn "Есть незакоммиченные изменения — делаем git stash."
    STASH_MSG=$(git stash push -m "update.sh auto stash @ $(date +%s)" 2>&1 || true)
    ok "Локальные изменения засташены."
fi

info "2/4. git pull origin..."
if git remote -v 2>/dev/null | grep -q "Attam2213/server-promvpn"; then
    git pull --ff-only origin main || git pull --ff-only origin master || git pull
else
    warn "Remote origin не указывает на Attam2213/server-promvpn — пробуем просто git pull"
    git pull
fi
AFTER=$(git rev-parse HEAD || echo "unknown")
if [[ "$BEFORE" != "$AFTER" ]]; then
    ok "Обновлено: ${BEFORE:0:8} → ${AFTER:0:8}"
    if command -v git >/dev/null && git log --oneline -n 3 >/dev/null 2>&1; then
        echo "----- Последние 3 коммита -----"
        git log --oneline -n 3
        echo "-------------------------------"
    fi
else
    ok "Уже последняя версия (изменений нет)."
fi

info "3/4. Обновляем Python зависимости..."
if [[ ! -d "$VENV_DIR" ]]; then
    warn "venv не найден — создаём..."
    python3 -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt" --quiet
ok "pip install -r requirements.txt — готово."

info "4/4. Перезапускаем systemd сервис $SERVICE_NAME..."
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    systemctl restart "$SERVICE_NAME"
    sleep 2
    systemctl --no-pager status "$SERVICE_NAME" --lines=5 || true
    ok "Сервис $SERVICE_NAME перезапущен."
else
    warn "Юнит $SERVICE_NAME не найден в systemd."
    echo "  Запусти install.sh для регистрации сервиса:"
    echo "    sudo bash $PROJECT_ROOT/install.sh"
fi

PORT="${APP_PORT:-8000}"
HEALTH=$(curl -s --max-time 5 "http://127.0.0.1:${PORT}/api/health" || echo "")
if echo "$HEALTH" | grep -q "ok"; then
    ok "Healthcheck прошёл: /api/health -> $HEALTH"
else
    warn "Healthcheck не прошёл — смотри journalctl -u $SERVICE_NAME -f"
fi

if [[ -n "$STASH_MSG" ]]; then
    info "Локальный stash сохранён. Восстановить: git stash pop"
fi

echo ""
echo -e "${GREEN}ОБНОВЛЕНИЕ ЗАВЕРШЕНО${NC}."
echo ""
