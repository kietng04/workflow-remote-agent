#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--wait" ]]; then
  shift
  exec python3 "$BASE_DIR/telegram_bot.py" wait-and-send --text "${1:?missing message}"
fi

exec python3 "$BASE_DIR/telegram_bot.py" send --text "${1:?missing message}"
