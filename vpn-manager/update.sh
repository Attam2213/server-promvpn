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

cd "$(dirname "$(readlink -f "$0")")"
PROJECT_ROOT="$(pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
VENV_DIR="$BACKEND_DIR/.venv"
SERVICE_NAME="${SERVICE_NAME:-vpn-manager}"
REPO_URL="${REPO_URL:-https://github.com/Attam2213/server-promvpn.git}"
SUBPATH_IN_REPO="${SUBPATH_IN_REPO:-vpn-manager}"

echo ""
echo "========================================================="
echo "  VPN VDS Manager — UPDATE (git pull + restart)"
echo "  PWD    : $PROJECT_ROOT"
echo "========================================================="
echo ""

GIT_DIR=""
if [[ -d "$PROJECT_ROOT/.git" ]]; then
    GIT_DIR="$PROJECT_ROOT"
elif [[ -d "$PROJECT_ROOT/../.git" ]]; then
    PARENT_REPO="$(cd "$PROJECT_ROOT/.." && pwd)"
    if [[ -d "$PARENT_REPO/$SUBPATH_IN_REPO" ]] && [[ "$(realpath "$PARENT_REPO/$SUBPATH_IN_REPO")" == "$(realpath "$PROJECT_ROOT")" ]]; then
        GIT_DIR="$PARENT_REPO"
    fi
fi

if [[ -z "$GIT_DIR" ]]; then
    warn "Локальный .git не найден — будет pull через временный clone + rsync."
    warn "Для чистоты рекомендуется перейти на git-based install:"
    echo "    rm -rf $PROJECT_ROOT"
    echo "    cd /opt && git clone $REPO_URL server-promvpn && ln -s /opt/server-promvpn/$SUBPATH_IN_REPO /opt/vpn-manager"

    TMP_DIR="$(mktemp -d /tmp/server-promvpn-update.XXXXXX)"
    trap 'rm -rf "$TMP_DIR"' EXIT

    info "1/4. Временное клонирование $REPO_URL..."
    if git clone --depth 1 "$REPO_URL" "$TMP_DIR/src" 2>/dev/null; then
        if [[ -d "$TMP_DIR/src/$SUBPATH_IN_REPO" ]]; then
            info "2/4. Rsync обновлённых файлов..."
            command -v rsync >/dev/null 2>&1 && {
                rsync -a --delete \
                    --exclude '.git/' \
                    --exclude '.venv/' \
                    --exclude '__pycache__/' \
                    --exclude '*.pyc' \
                    --exclude '*.db' \
                    --exclude 'vpn_users.json' \
                    "$TMP_DIR/src/$SUBPATH_IN_REPO/" "$PROJECT_ROOT/" && \
                    ok "Файлы обновлены из временного клона."
            } || {
                info "rsync не найден — используем cp -a..."
                rm -rf "$PROJECT_ROOT/backend" "$PROJECT_ROOT/frontend"
                cp -a "$TMP_DIR/src/$SUBPATH_IN_REPO/backend" "$PROJECT_ROOT/backend"
                cp -a "$TMP_DIR/src/$SUBPATH_IN_REPO/frontend" "$PROJECT_ROOT/frontend"
                cp -a "$TMP_DIR/src/$SUBPATH_IN_REPO/install.sh" "$PROJECT_ROOT/install.sh" 2>/dev/null || true
                cp -a "$TMP_DIR/src/$SUBPATH_IN_REPO/update.sh" "$PROJECT_ROOT/update.sh" 2>/dev/null || true
                cp -a "$TMP_DIR/src/$SUBPATH_IN_REPO/.gitignore" "$PROJECT_ROOT/.gitignore" 2>/dev/null || true
                ok "Файлы обновлены через cp."
            }
            rm -rf "$TMP_DIR/src"
        else
            err "В клонированной репе не найден подкаталог $SUBPATH_IN_REPO"
            exit 1
        fi
    else
        err "Не удалось клонировать $REPO_URL — проверь интернет / DNS / прокси."
        exit 1
    fi
else
    info "Найден git-репозиторий в $GIT_DIR"
    cd "$GIT_DIR"

    info "1/4. Сохраняем локальные правки (если есть)..."
    BEFORE=$(git rev-parse HEAD || echo "unknown")
    STASH_MSG=""
    if [[ -n "$(git status --porcelain)" ]]; then
        warn "Есть незакоммиченные изменения — делаем git stash."
        STASH_MSG=$(git stash push -m "update.sh auto stash @ $(date +%s)" 2>&1 || true)
        ok "Локальные изменения засташены."
    fi

    info "2/4. git pull origin..."
    REMOTE_URL="$(git remote get-url origin 2>/dev/null || echo "")"
    if echo "$REMOTE_URL" | grep -q "Attam2213/server-promvpn"; then
        git pull --ff-only origin main 2>&1 | tail -5 || git pull --ff-only origin master 2>&1 | tail -5 || git pull 2>&1 | tail -5
    else
        warn "Remote origin ($REMOTE_URL) не совпадает с Attam2213/server-promvpn — используем FETCH_HEAD"
        git fetch --depth 1 "$REPO_URL" main 2>&1 | tail -3
        git merge --ff-only FETCH_HEAD 2>&1 | tail -3 || true
    fi
    AFTER=$(git rev-parse HEAD || echo "unknown")
    if [[ "$BEFORE" != "$AFTER" ]]; then
        ok "Обновлено: ${BEFORE:0:8} → ${AFTER:0:8}"
        command -v git >/dev/null && git log --oneline -n 3 >/dev/null 2>&1 && {
            echo "----- Последние 3 коммита -----"
            git log --oneline -n 3
            echo "-------------------------------"
        } || true
    else
        ok "Уже последняя версия (изменений нет)."
    fi
fi

info "3/4. Обновляем Python зависимости..."
if [[ ! -d "$VENV_DIR" ]]; then
    warn "venv не найден — создаём..."
    python3 -m venv "$VENV_DIR" || true
fi
"$VENV_DIR/bin/pip" install --upgrade pip --quiet || true
"$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt" --quiet || true
if "$VENV_DIR/bin/python" -c "import fastapi" 2>/dev/null; then
    ok "pip install -r requirements.txt — готово."
else
    warn "pip install прошёл с ошибками — попробуй руками:"
    echo "    $VENV_DIR/bin/pip install -r $BACKEND_DIR/requirements.txt"
fi

info "4/4. Перезапускаем systemd сервис $SERVICE_NAME..."
if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE_NAME}.service"; then
    systemctl restart "$SERVICE_NAME" || true
    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Сервис $SERVICE_NAME перезапущен, работает."
    else
        warn "Сервис $SERVICE_NAME не запустился. Последние логи:"
        journalctl -u "$SERVICE_NAME" -n 20 --no-pager || true
    fi
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
    info "Локальный stash сохранён. Восстановить: cd $GIT_DIR && git stash pop"
fi

echo ""
echo -e "${GREEN}ОБНОВЛЕНИЕ ЗАВЕРШЕНО${NC}."
echo ""
