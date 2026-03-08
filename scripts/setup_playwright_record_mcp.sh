#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="$HOME/.codex/mcp-servers/playwright-record-mcp"
PATCH_FILE=""
REPO_URL="https://github.com/korwabs/playwright-record-mcp.git"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-dir)
      TARGET_DIR="$2"
      shift 2
      ;;
    --patch)
      PATCH_FILE="$2"
      shift 2
      ;;
    *)
      echo "Khong ho tro tham so: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$PATCH_FILE" ]]; then
  echo "Can truyen --patch <path>" >&2
  exit 1
fi

log() {
  printf '[mcp] %s\n' "$1"
}

mkdir -p "$(dirname "$TARGET_DIR")"

if [[ ! -d "$TARGET_DIR/.git" ]]; then
  log "Clone $REPO_URL vao $TARGET_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
else
  log "Su dung repo da ton tai tai $TARGET_DIR"
fi

if git -C "$TARGET_DIR" apply --check "$PATCH_FILE" >/dev/null 2>&1; then
  log "Apply patch local"
  git -C "$TARGET_DIR" apply "$PATCH_FILE"
elif git -C "$TARGET_DIR" apply --reverse --check "$PATCH_FILE" >/dev/null 2>&1; then
  log "Patch da duoc apply truoc do"
else
  echo "Patch khong apply duoc va cung khong phai da apply san. Hay kiem tra repo $TARGET_DIR" >&2
  exit 1
fi

log "Cai dependency va build"
(
  cd "$TARGET_DIR"
  npm install
  npm run build
)

log "Playwright Record MCP da san sang"
