#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ASSETS_DIR="$ROOT_DIR/assets/telegram-bot-cli"
TARGET_HOME="${TARGET_HOME:-$HOME}"
TELEGRAM_DIR="${TELEGRAM_DIR:-$TARGET_HOME/telegram-bot-cli}"
PLAYWRIGHT_RECORD_DIR="${PLAYWRIGHT_RECORD_DIR:-$TARGET_HOME/.codex/mcp-servers/playwright-record-mcp}"
CODEX_CONFIG="${CODEX_CONFIG:-$TARGET_HOME/.codex/config.toml}"
SERVICE_NAME="telegram-codex-bridge.service"
SERVICE_TARGET="/etc/systemd/system/$SERVICE_NAME"

SKIP_APT=0
SKIP_VERIFY=0
SKIP_MCP=0
SKIP_SERVICE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-apt)
      SKIP_APT=1
      shift
      ;;
    --skip-verify)
      SKIP_VERIFY=1
      shift
      ;;
    --skip-mcp)
      SKIP_MCP=1
      shift
      ;;
    --skip-service)
      SKIP_SERVICE=1
      shift
      ;;
    *)
      echo "Khong ho tro tham so: $1" >&2
      exit 1
      ;;
  esac
done

log() {
  printf '[install] %s\n' "$1"
}

ensure_packages() {
  if [[ "$SKIP_APT" -eq 1 ]]; then
    log "Bo qua apt install theo yeu cau."
    return
  fi

  log "Cai package he thong can thiet."
  sudo apt-get update
  sudo apt-get install -y curl ffmpeg git nodejs npm python3 rsync
}

sync_telegram_cli() {
  log "Dong bo Telegram CLI vao $TELEGRAM_DIR"
  mkdir -p "$TELEGRAM_DIR"
  rsync -a \
    --delete \
    --exclude '.env' \
    --exclude '.telegram_bot_state.json' \
    --exclude 'bridge.log' \
    --exclude '__pycache__/' \
    --exclude 'converted_videos/' \
    --exclude 'handoffs/' \
    "$ASSETS_DIR/" "$TELEGRAM_DIR/"

  if [[ ! -f "$TELEGRAM_DIR/.env" ]]; then
    cp "$ASSETS_DIR/.env.example" "$TELEGRAM_DIR/.env"
    log "Da tao $TELEGRAM_DIR/.env tu template. Hay dien gia tri that neu can."
  fi

  chmod +x \
    "$TELEGRAM_DIR/start_codex_bridge.sh" \
    "$TELEGRAM_DIR/send_telegram.sh" \
    "$TELEGRAM_DIR/telegram_bot.py" \
    "$TELEGRAM_DIR/telegram_codex_bridge.py" \
    "$TELEGRAM_DIR/codex_handoff.py"
}

env_is_ready() {
  local env_file="$1"
  python3 - "$env_file" <<'PY'
from pathlib import Path
import sys

required = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_CHAT_ID",
    "CODEX_FIXED_THREAD_ID",
    "CODEX_WORKDIR",
]

path = Path(sys.argv[1])
values = {}
if path.exists():
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

for key in required:
    value = values.get(key, "")
    if not value or value in {"CHANGE_ME", "<fill-me>"}:
        raise SystemExit(1)
raise SystemExit(0)
PY
}

install_service() {
  if [[ "$SKIP_SERVICE" -eq 1 ]]; then
    log "Bo qua cai dat service theo yeu cau."
    return
  fi

  log "Cai systemd service $SERVICE_NAME"
  sudo install -m 0644 "$TELEGRAM_DIR/$SERVICE_NAME" "$SERVICE_TARGET"
  sudo systemctl daemon-reload

  if env_is_ready "$TELEGRAM_DIR/.env"; then
    log ".env da du bien. Enable va start service."
    sudo systemctl enable --now "$SERVICE_NAME"
  else
    log ".env chua du bien can thiet. Se stop/disable service de tranh crash loop."
    sudo systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    log "Dien $TELEGRAM_DIR/.env roi chay lai ./scripts/install.sh"
  fi
}

configure_codex() {
  log "Cap nhat Codex config tai $CODEX_CONFIG"
  python3 "$ROOT_DIR/scripts/configure_codex_config.py" \
    --config "$CODEX_CONFIG" \
    --playwright-record-dir "$PLAYWRIGHT_RECORD_DIR"
}

setup_mcp() {
  if [[ "$SKIP_MCP" -eq 1 ]]; then
    log "Bo qua Playwright Record MCP theo yeu cau."
    return
  fi

  log "Clone/patch/build Playwright Record MCP"
  "$ROOT_DIR/scripts/setup_playwright_record_mcp.sh" \
    --target-dir "$PLAYWRIGHT_RECORD_DIR" \
    --patch "$ROOT_DIR/patches/playwright-record-mcp.patch"
}

verify_install() {
  if [[ "$SKIP_VERIFY" -eq 1 ]]; then
    log "Bo qua verify theo yeu cau."
    return
  fi
  log "Chay verify sau cai dat."
  "$ROOT_DIR/scripts/verify_install.sh"
}

ensure_packages
sync_telegram_cli
setup_mcp
configure_codex
install_service
verify_install

log "Hoan tat."
