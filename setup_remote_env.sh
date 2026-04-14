#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# setup_remote_env.sh — установка VEX EXPRESS Bot на чистый VPS
# ─────────────────────────────────────────────────────────────
# Назначение:
#   Устанавливает всё нужное на свежем Ubuntu 22.04+ VPS,
#   чтобы бот жил 24/7 даже когда ноутбук выключен.
#
# Запускать ОТ ROOT:
#   curl -sSL <URL>/setup_remote_env.sh | sudo bash
#   либо:
#   sudo bash setup_remote_env.sh
# ─────────────────────────────────────────────────────────────

set -e

APP_DIR="/opt/vex-express-bot"
REPO_URL="https://github.com/goodfipi-dotcom/vex-express-bot.git"
SERVICE_FILE="/etc/systemd/system/vex-bot.service"
PYTHON="python3.11"

log() { echo "→ $*"; }

# ── проверки ─────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Запусти через sudo (нужны права root для systemd)"
    exit 1
fi

# ── 1. системные пакеты ──────────────────────────────────────
log "обновляю apt"
apt-get update -qq

log "ставлю python 3.11, git, curl"
apt-get install -y -qq $PYTHON ${PYTHON}-venv python3-pip git curl

# ── 2. код ───────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    log "репозиторий уже есть — git pull"
    cd "$APP_DIR" && git pull
else
    log "клонирую $REPO_URL → $APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 3. виртуальное окружение + зависимости ───────────────────
log "создаю venv"
$PYTHON -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -U pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ── 4. .env (шаблон если ещё нет) ────────────────────────────
if [ ! -f "$APP_DIR/.env" ]; then
    log "создаю .env (нужно заполнить!)"
    cat > "$APP_DIR/.env" <<'EOF'
BOT_TOKEN=
PAYMENT_PROVIDER_TOKEN=

MARZBAN_URL=
MARZBAN_USERNAME=admin
MARZBAN_PASSWORD=
INBOUND_TAG=VLESS TCP REALITY

WEBAPP_URL=https://vex-express-tma.vercel.app
SUPPORT_USERNAME=vex_support
EOF
    chmod 600 "$APP_DIR/.env"
fi

# ── 5. systemd unit (автозапуск при рестарте сервера) ────────
log "создаю systemd unit: $SERVICE_FILE"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=VEX EXPRESS Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vex-bot

# ── 6. итог ──────────────────────────────────────────────────
cat <<EOF

✅ Установка завершена.

ДАЛЕЕ:
  1. Заполни .env:          nano $APP_DIR/.env
  2. Запусти бота:          systemctl start vex-bot
  3. Проверь статус:        systemctl status vex-bot
  4. Смотри логи в реальном времени:
                            journalctl -u vex-bot -f
  5. /health endpoint:      curl http://127.0.0.1:8080/health

Для перезапуска после изменений:  systemctl restart vex-bot
Для остановки:                    systemctl stop vex-bot
EOF
