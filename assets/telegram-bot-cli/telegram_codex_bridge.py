#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
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

def format_worked_duration(elapsed_seconds: int) -> str:
    minutes, seconds = divmod(elapsed_seconds, 60)
    return f"Worked for {minutes} minutes {seconds} seconds"


def append_worked_duration(reply_text: str, started_at_monotonic: float) -> str:
    elapsed_seconds = max(0, int(time.monotonic() - started_at_monotonic))
    return f"{reply_text.rstrip()}\n\n{format_worked_duration(elapsed_seconds)}"


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


def build_codex_prompt(user_text: str) -> str:
    telegram_cli = BASE_DIR / "telegram_bot.py"
    return (
        "Tin nhan nguoi dung tu Telegram:\n"
        f"{user_text.strip()}\n\n"
        "Huong dan van hanh bat buoc cho luot nay:\n"
        "- Lam viec theo AGENTS.md va instruction cua repo hien tai.\n"
        "- Neu day chi la chao hoi hoac hoi dap ngan khong can thao tac he thong, tra loi ngan gon binh thuong.\n"
        "- Neu day la task co deliverable hoac co the demo duoc, khong duoc dung lai o text-only.\n"
        "- Voi task demonstrable, UI, browser flow, setup he thong, hoac ket qua co the quay lai duoc: truoc khi bao DONE phai record proof video va gui video do qua Telegram.\n"
        f"- Lenh gui video san co tren may: python3 {telegram_cli} send-file --path /path/to/video.webm --as video --caption \"proof\"\n"
        "- Cau tra loi cuoi cho task demonstrable phai neu ro duong dan video, Telegram message_id, va ket qua xac thuc. Neu chua gui duoc video thi phai BLOCKED va noi ro blocker.\n"
        "- Khong duoc noi DONE neu chua xong buoc video + Telegram trong truong hop task co the demo duoc.\n"
        "- KHONG duoc compact context, handoff, start thread moi, hoac doi active thread tru khi nguoi dung noi ro yeu cau do.\n"
        "- Neu tin nhan hien tai khong nhac den compact/handoff/start chat moi thi phai tiep tuc tren active thread hien tai.\n\n"
        "- Neu nguoi dung yeu cau quay video cho mot app/web/luong cu the nhu login, form, dashboard, chatbot, CRUD, thi video bat buoc phai quay dung flow do tren app that.\n"
        "- Khong duoc thay the bang video proof cua handoff, README, file JSON, trang tong hop, hay artifact khong lien quan den flow nguoi dung vua yeu cau.\n"
        "- Voi web flow, uu tien dung MCP browser / Playwright / playwright_record de quay va xac thuc truc tiep tren giao dien that.\n\n"
        "Bat dau xu ly yeu cau cua nguoi dung."
    )


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
    started_at_monotonic = time.monotonic()
    codex_prompt = build_codex_prompt(incoming_text)
    reply_text = run_codex_resume(
        thread_id=thread_id,
        prompt=codex_prompt,
        workdir=codex_workdir,
        yolo=yolo,
        codex_bin=codex_bin,
    )
    reply_text = append_worked_duration(reply_text, started_at_monotonic)

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
