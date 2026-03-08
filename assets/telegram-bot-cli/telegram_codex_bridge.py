#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram_bot import (
    TelegramBotClient,
    ENV_FILE,
    extract_chat,
    fail,
    load_env_file,
    load_state,
    resolve_token,
    save_state,
)


BASE_DIR = Path(__file__).resolve().parent
BRIDGE_LAST_UPDATE_KEY = "codex_bridge_last_update_id"
ACTIVE_THREAD_KEY = "codex_bridge_thread_id"
DEFAULT_ALLOWED_UPDATES = ["message"]


def log(message: str) -> None:
    print(message, flush=True)


def resolve_required_env(key: str, cli_value: str | int | None) -> str:
    load_env_file(ENV_FILE)
    value = cli_value if cli_value is not None else os.environ.get(key)
    if value is None or str(value).strip() == "":
        fail(f"Thieu cau hinh {key}. Hay dat trong .env hoac truyen qua CLI.")
    return str(value)


def extract_message(update: dict[str, Any]) -> dict[str, Any] | None:
    message = update.get("message")
    return message if isinstance(message, dict) else None


def extract_incoming_text(update: dict[str, Any]) -> str | None:
    message = extract_message(update)
    if not message:
        return None
    sender = message.get("from")
    if isinstance(sender, dict) and sender.get("is_bot"):
        return None
    text = message.get("text")
    return text if isinstance(text, str) and text.strip() else None


def split_message(text: str, max_chars: int = 4000) -> list[str]:
    remaining = text.strip()
    if not remaining:
        return ["(empty response)"]

    chunks: list[str] = []
    while len(remaining) > max_chars:
        cut = remaining.rfind("\n\n", 0, max_chars)
        if cut < 1000:
            cut = remaining.rfind("\n", 0, max_chars)
        if cut < 1000:
            cut = max_chars
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


@functools.lru_cache(maxsize=64)
def find_session_file(thread_id: str) -> Path | None:
    sessions_root = Path.home() / ".codex" / "sessions"
    matches = sorted(sessions_root.rglob(f"*{thread_id}.jsonl"))
    return matches[-1] if matches else None


@functools.lru_cache(maxsize=64)
def get_session_started_at(thread_id: str) -> datetime | None:
    session_file = find_session_file(thread_id)
    if not session_file:
        return None

    try:
        with session_file.open(encoding="utf-8") as handle:
            first_line = handle.readline().strip()
    except OSError:
        return None

    if not first_line:
        return None

    try:
        payload = json.loads(first_line)
    except json.JSONDecodeError:
        return None

    session_meta = payload.get("payload") if payload.get("type") == "session_meta" else None
    timestamp = None
    if isinstance(session_meta, dict):
        timestamp = session_meta.get("timestamp")
    if not timestamp:
        timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str):
        return None

    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def format_worked_duration(thread_id: str) -> str | None:
    started_at = get_session_started_at(thread_id)
    if not started_at:
        return None
    elapsed_seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
    minutes, seconds = divmod(elapsed_seconds, 60)
    return f"Worked for {minutes} minutes {seconds} seconds"


def append_worked_duration(reply_text: str, thread_id: str) -> str:
    worked_text = format_worked_duration(thread_id)
    if not worked_text:
        return reply_text
    return f"{reply_text.rstrip()}\n\n{worked_text}"


def load_active_thread_id(default_thread_id: str) -> str:
    state = load_state()
    saved_thread_id = state.get(ACTIVE_THREAD_KEY)
    if isinstance(saved_thread_id, str) and saved_thread_id.strip():
        return saved_thread_id.strip()
    return default_thread_id


def merge_state(changes: dict[str, Any]) -> dict[str, Any]:
    state = load_state()
    state.update(changes)
    save_state(state)
    return state


def run_codex_resume(
    *,
    thread_id: str,
    prompt: str,
    workdir: str,
    yolo: bool,
    codex_bin: str,
) -> str:
    log(f"[codex] resume thread {thread_id}")
    command = [
        codex_bin,
        "exec",
        "resume",
        thread_id,
        "--json",
        "--skip-git-repo-check",
    ]
    if yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    command.append(prompt)

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=workdir,
    )

    reply_text: str | None = None
    json_lines: list[dict[str, Any]] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        json_lines.append(payload)
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            reply_text = text.strip()

    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "Codex process failed."
        fail(f"Codex resume loi: {details}")

    if reply_text:
        log(f"[codex] received {len(reply_text)} chars")
        return reply_text

    fail(
        "Codex khong tra ve agent_message hop le. "
        f"Stdout da nhan {len(json_lines)} event, stderr='{completed.stderr.strip()}'."
    )
    raise AssertionError("unreachable")


def handle_update(
    *,
    client: TelegramBotClient,
    update: dict[str, Any],
    allowed_chat_id: int,
    default_thread_id: str,
    codex_workdir: str,
    yolo: bool,
    codex_bin: str,
) -> None:
    chat = extract_chat(update)
    if not chat or int(chat.get("id", 0)) != allowed_chat_id:
        return

    message = extract_message(update)
    if not message:
        return

    incoming_text = extract_incoming_text(update)
    if incoming_text is None:
        log("[telegram] non-text message ignored with notice")
        client.send_message(
            chat_id=allowed_chat_id,
            text="Bot nay hien chi xu ly tin nhan text.",
            disable_notification=True,
        )
        return

    if incoming_text == "/start":
        log("[telegram] handled /start locally")
        client.send_message(
            chat_id=allowed_chat_id,
            text="Bridge Telegram -> Codex dang chay. Cu nhan tin, toi se resume theo thread dang active.",
            disable_notification=True,
        )
        return

    thread_id = load_active_thread_id(default_thread_id)
    log(f"[bridge] active thread={thread_id}")
    log(f"[telegram] incoming text: {incoming_text[:120]!r}")
    reply_text = run_codex_resume(
        thread_id=thread_id,
        prompt=incoming_text,
        workdir=codex_workdir,
        yolo=yolo,
        codex_bin=codex_bin,
    )
    reply_text = append_worked_duration(reply_text, thread_id)

    for chunk in split_message(reply_text):
        client.send_message(chat_id=allowed_chat_id, text=chunk)
    log("[telegram] reply sent")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bridge polling giua Telegram va Codex resume thread co dinh."
    )
    parser.add_argument("--token", help="Telegram bot token. Mac dinh doc tu .env.")
    parser.add_argument("--chat-id", type=int, help="Chat ID Telegram duoc phep.")
    parser.add_argument("--thread-id", help="Codex thread_id co dinh de resume.")
    parser.add_argument(
        "--workdir",
        help="Thu muc chay Codex. Mac dinh doc tu CODEX_WORKDIR trong .env hoac /home/ubuntu/clinic-projects.",
    )
    parser.add_argument("--codex-bin", default="codex", help="Duong dan binary Codex.")
    parser.add_argument("--poll-timeout", type=int, default=20, help="Long poll timeout (giay).")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="Thoi gian ngu giua cac vong rong.")
    parser.add_argument("--offset", type=int, help="Offset bat dau, dung de replay/test.")
    parser.add_argument("--once", action="store_true", help="Chay mot vong roi thoat.")
    parser.add_argument(
        "--no-yolo",
        action="store_true",
        help="Tat che do bypass approvals. Mac dinh la bat.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    token = resolve_token(args.token)
    load_env_file(ENV_FILE)

    allowed_chat_id = int(resolve_required_env("TELEGRAM_ALLOWED_CHAT_ID", args.chat_id))
    thread_id = resolve_required_env("CODEX_FIXED_THREAD_ID", args.thread_id)
    codex_workdir = args.workdir or os.environ.get("CODEX_WORKDIR", "/home/ubuntu/clinic-projects")
    yolo = not args.no_yolo and os.environ.get("CODEX_USE_YOLO", "true").lower() != "false"

    client = TelegramBotClient(token)
    state = load_state()
    offset = args.offset
    if offset is None:
        saved = state.get(BRIDGE_LAST_UPDATE_KEY)
        if saved is not None:
            offset = int(saved) + 1
    if not state.get(ACTIVE_THREAD_KEY):
        state[ACTIVE_THREAD_KEY] = thread_id
        save_state(state)

    while True:
        log(f"[bridge] polling offset={offset}")
        updates = client.get_updates(
            offset=offset,
            timeout=args.poll_timeout,
            allowed_updates=DEFAULT_ALLOWED_UPDATES,
        )

        if not updates:
            if args.once:
                return
            time.sleep(args.idle_sleep)
            continue

        for update in updates:
            update_id = int(update["update_id"])
            log(f"[bridge] processing update_id={update_id}")
            try:
                handle_update(
                    client=client,
                    update=update,
                    allowed_chat_id=allowed_chat_id,
                    default_thread_id=thread_id,
                    codex_workdir=codex_workdir,
                    yolo=yolo,
                    codex_bin=args.codex_bin,
                )
            except SystemExit as exc:
                error_text = str(exc) or "Khong ro loi"
                log(f"[bridge] system exit error: {error_text}")
                client.send_message(
                    chat_id=allowed_chat_id,
                    text=f"Bridge loi: {error_text[:3500]}",
                )
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                log(f"[bridge] unexpected error: {exc}")
                client.send_message(
                    chat_id=allowed_chat_id,
                    text=f"Bridge loi khong mong doi: {str(exc)[:3500]}",
                )
            finally:
                merge_state({BRIDGE_LAST_UPDATE_KEY: update_id})
                offset = update_id + 1

        if args.once:
            return


if __name__ == "__main__":
    main()
