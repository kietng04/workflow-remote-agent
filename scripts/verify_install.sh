#!/usr/bin/env bash
set -euo pipefail

TARGET_HOME="${TARGET_HOME:-$HOME}"
TELEGRAM_DIR="${TELEGRAM_DIR:-$TARGET_HOME/telegram-bot-cli}"
PLAYWRIGHT_RECORD_DIR="${PLAYWRIGHT_RECORD_DIR:-$TARGET_HOME/.codex/mcp-servers/playwright-record-mcp}"
CODEX_CONFIG="${CODEX_CONFIG:-$TARGET_HOME/.codex/config.toml}"
SERVICE_NAME="telegram-codex-bridge.service"

log() {
  printf '[verify] %s\n' "$1"
}

fail() {
  printf '[verify] %s\n' "$1" >&2
  exit 1
}

check_file() {
  [[ -f "$1" ]] || fail "Thieu file: $1"
}

check_dir() {
  [[ -d "$1" ]] || fail "Thieu thu muc: $1"
}

command -v codex >/dev/null 2>&1 || fail "Khong tim thay binary codex"
command -v python3 >/dev/null 2>&1 || fail "Khong tim thay python3"

check_dir "$TELEGRAM_DIR"
check_file "$TELEGRAM_DIR/telegram_bot.py"
check_file "$TELEGRAM_DIR/telegram_codex_bridge.py"
check_file "$TELEGRAM_DIR/codex_handoff.py"
check_file "$TELEGRAM_DIR/start_codex_bridge.sh"
check_file "$TELEGRAM_DIR/telegram-codex-bridge.service"
check_file "$TELEGRAM_DIR/.env"

python3 -m py_compile \
  "$TELEGRAM_DIR/telegram_bot.py" \
  "$TELEGRAM_DIR/telegram_codex_bridge.py" \
  "$TELEGRAM_DIR/codex_handoff.py"

check_dir "$PLAYWRIGHT_RECORD_DIR"
check_file "$PLAYWRIGHT_RECORD_DIR/cli.js"
check_file "$PLAYWRIGHT_RECORD_DIR/lib/context.js"
check_file "$PLAYWRIGHT_RECORD_DIR/lib/tools/snapshot.js"
check_file "$PLAYWRIGHT_RECORD_DIR/lib/tools/screen.js"
check_file "$CODEX_CONFIG"

grep -q '^\[mcp_servers.playwright_record\]' "$CODEX_CONFIG" || fail "Khong thay block mcp_servers.playwright_record trong $CODEX_CONFIG"
grep -q 'record-video' "$CODEX_CONFIG" || fail "Khong thay co record-video trong $CODEX_CONFIG"

if systemctl list-unit-files "$SERVICE_NAME" >/dev/null 2>&1; then
  log "Service $SERVICE_NAME da duoc cai"
  if systemctl is-enabled "$SERVICE_NAME" >/dev/null 2>&1; then
    log "Service $SERVICE_NAME dang enabled"
  else
    log "Service $SERVICE_NAME chua enabled"
  fi
  if systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
    log "Service $SERVICE_NAME dang active"
  else
    log "Service $SERVICE_NAME chua active"
  fi
else
  fail "Service $SERVICE_NAME chua duoc cai"
fi

if python3 - "$TELEGRAM_DIR/.env" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
values = {}
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip('"').strip("'")
required = ["TELEGRAM_BOT_TOKEN"]
for key in required:
    if not values.get(key):
        raise SystemExit(1)
PY
then
  log "Thu get-me voi Telegram"
  python3 "$TELEGRAM_DIR/telegram_bot.py" get-me >/dev/null
fi

log "Verify thanh cong"
