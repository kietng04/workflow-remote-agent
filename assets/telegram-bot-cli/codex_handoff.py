#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telegram_bot import ENV_FILE, TelegramBotClient, fail, load_env_file, load_state, resolve_token, save_state
from telegram_codex_bridge import ACTIVE_THREAD_KEY, format_worked_duration, split_message


BASE_DIR = Path(__file__).resolve().parent
HANDOFFS_DIR = BASE_DIR / "handoffs"
LAST_HANDOFF_KEY = "codex_bridge_last_handoff"

SUMMARY_PROMPT = """Ban dang chuan bi handoff cho mot phien Codex moi.

Hay tom tat thread hien tai thanh mot ban handoff bang tieng Viet, van ban thuong, gon nhung du thong tin.
Bat buoc co cac muc theo dung ten sau:
- Muc tieu
- Da lam
- Trang thai hien tai
- Tep va duong dan quan trong
- Lenh da chay va cach xac thuc
- Viec tiep theo
- Rang buoc / luu y

Yeu cau:
- Khong dung markdown code fence.
- Khong chao hoi.
- Khong hoi lai nguoi dung.
- Khong them thong tin ngoai thread hien tai.
- Uu tien thong tin giup mot Codex moi tiep tuc cong viec ngay.
"""


def build_bootstrap_prompt(summary: str, source_thread_id: str, worked_text: str | None) -> str:
    worked_line = worked_text or "Worked for 0 minutes 0 seconds"
    return (
        "Ban dang nhan handoff tu mot thread Codex truoc. "
        "Hay luu noi dung ben duoi lam context bat dau cho phien moi.\n\n"
        f"Source thread id: {source_thread_id}\n"
        f"{worked_line}\n\n"
        "Tom tat handoff:\n"
        f"{summary.strip()}\n\n"
        "Khong can thuc hien cong viec nao khac. "
        'Chi tra loi dung mot dong: HANDOFF READY'
    )


def run_codex_json(command: list[str], *, workdir: str) -> tuple[list[dict[str, Any]], subprocess.CompletedProcess[str]]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=workdir,
    )

    events: list[dict[str, Any]] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)

    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "Codex process failed."
        fail(f"Codex loi: {details}")
    return events, completed


def extract_last_agent_message(events: list[dict[str, Any]]) -> str:
    reply_text: str | None = None
    for payload in events:
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            reply_text = text.strip()
    if not reply_text:
        fail("Codex khong tra ve agent_message hop le.")
    return reply_text


def extract_thread_id(events: list[dict[str, Any]]) -> str:
    for payload in events:
        if payload.get("type") != "thread.started":
            continue
        thread_id = payload.get("thread_id")
        if isinstance(thread_id, str) and thread_id.strip():
            return thread_id.strip()
    fail("Khong lay duoc thread_id moi tu Codex.")
    raise AssertionError("unreachable")


def summarize_thread(
    *,
    source_thread_id: str,
    workdir: str,
    yolo: bool,
    codex_bin: str,
) -> str:
    command = [
        codex_bin,
        "exec",
        "resume",
        source_thread_id,
        "--json",
        "--skip-git-repo-check",
    ]
    if yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    command.append(SUMMARY_PROMPT)
    events, _ = run_codex_json(command, workdir=workdir)
    return extract_last_agent_message(events)


def start_new_thread(
    *,
    prompt: str,
    workdir: str,
    yolo: bool,
    codex_bin: str,
) -> tuple[str, str]:
    command = [
        codex_bin,
        "exec",
        "--json",
        "--skip-git-repo-check",
    ]
    if yolo:
        command.append("--dangerously-bypass-approvals-and-sandbox")
    command.append(prompt)
    events, _ = run_codex_json(command, workdir=workdir)
    return extract_thread_id(events), extract_last_agent_message(events)


def resolve_source_thread_id(cli_thread_id: str | None) -> str:
    load_env_file(ENV_FILE)
    state = load_state()
    candidates = [
        cli_thread_id,
        state.get(ACTIVE_THREAD_KEY),
        os.environ.get("CODEX_FIXED_THREAD_ID"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    fail("Khong tim thay source thread id. Hay truyen --source-thread-id hoac cau hinh CODEX_FIXED_THREAD_ID.")
    raise AssertionError("unreachable")


def resolve_chat_id(cli_chat_id: int | None) -> int:
    load_env_file(ENV_FILE)
    state = load_state()
    candidates = [
        cli_chat_id,
        state.get("default_chat_id"),
        os.environ.get("TELEGRAM_ALLOWED_CHAT_ID"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        return int(candidate)
    fail("Khong tim thay chat_id Telegram. Hay truyen --chat-id hoac cau hinh TELEGRAM_ALLOWED_CHAT_ID.")
    raise AssertionError("unreachable")


def upsert_env_value(path: Path, key: str, value: str) -> None:
    existing_lines: list[str] = []
    found = False
    if path.exists():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    updated_lines: list[str] = []
    for line in existing_lines:
        if line.startswith(f"{key}="):
            updated_lines.append(f"{key}={value}")
            found = True
        else:
            updated_lines.append(line)

    if not found:
        updated_lines.append(f"{key}={value}")

    path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")


def store_handoff_artifacts(
    *,
    source_thread_id: str,
    new_thread_id: str,
    summary_text: str,
    worked_seconds: int,
    worked_text: str | None,
    bootstrap_reply: str,
) -> tuple[Path, Path]:
    HANDOFFS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    summary_file = HANDOFFS_DIR / f"handoff-{stamp}-{new_thread_id}.md"
    metadata_file = HANDOFFS_DIR / f"handoff-{stamp}-{new_thread_id}.json"

    summary_file.write_text(summary_text.rstrip() + "\n", encoding="utf-8")
    metadata_file.write_text(
        json.dumps(
            {
                "source_thread_id": source_thread_id,
                "new_thread_id": new_thread_id,
                "worked_seconds": worked_seconds,
                "worked_text": worked_text,
                "summary_file": str(summary_file),
                "bootstrap_reply": bootstrap_reply,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary_file, metadata_file


def send_handoff_telegram_message(
    *,
    client: TelegramBotClient,
    chat_id: int,
    source_thread_id: str,
    new_thread_id: str,
    worked_text: str | None,
    summary_text: str,
) -> list[int]:
    header_lines = [
        "Handoff Codex da xong.",
        f"Thread cu: {source_thread_id}",
        f"Thread moi: {new_thread_id}",
        worked_text or "Worked for 0 minutes 0 seconds",
        "",
        "Tom tat:",
        summary_text.strip(),
    ]
    message_ids: list[int] = []
    for chunk in split_message("\n".join(header_lines)):
        result = client.send_message(chat_id=chat_id, text=chunk)
        message_ids.append(int(result["message_id"]))
    return message_ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tom tat thread Codex hien tai, tao thread moi, cap nhat bridge state va thong bao qua Telegram."
    )
    parser.add_argument("--source-thread-id", help="Thread cu can handoff. Mac dinh lay tu state/.env.")
    parser.add_argument("--chat-id", type=int, help="Chat Telegram de gui thong bao.")
    parser.add_argument(
        "--workdir",
        help="Thu muc chay Codex. Mac dinh lay tu CODEX_WORKDIR hoac /home/ubuntu/clinic-projects.",
    )
    parser.add_argument("--codex-bin", default="codex", help="Duong dan binary Codex.")
    parser.add_argument("--token", help="Telegram bot token. Mac dinh doc tu .env.")
    parser.add_argument("--no-telegram", action="store_true", help="Khong gui thong bao Telegram.")
    parser.add_argument(
        "--no-yolo",
        action="store_true",
        help="Tat che do bypass approvals. Mac dinh la bat.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    load_env_file(ENV_FILE)

    source_thread_id = resolve_source_thread_id(args.source_thread_id)
    workdir = args.workdir or os.environ.get("CODEX_WORKDIR", "/home/ubuntu/clinic-projects")
    yolo = not args.no_yolo and os.environ.get("CODEX_USE_YOLO", "true").lower() != "false"
    worked_text = format_worked_duration(source_thread_id)
    worked_seconds = 0
    if worked_text:
        parts = worked_text.removeprefix("Worked for ").split()
        if len(parts) >= 4:
            worked_seconds = int(parts[0]) * 60 + int(parts[2])

    summary_text = summarize_thread(
        source_thread_id=source_thread_id,
        workdir=workdir,
        yolo=yolo,
        codex_bin=args.codex_bin,
    )

    bootstrap_prompt = build_bootstrap_prompt(summary_text, source_thread_id, worked_text)
    new_thread_id, bootstrap_reply = start_new_thread(
        prompt=bootstrap_prompt,
        workdir=workdir,
        yolo=yolo,
        codex_bin=args.codex_bin,
    )

    summary_file, metadata_file = store_handoff_artifacts(
        source_thread_id=source_thread_id,
        new_thread_id=new_thread_id,
        summary_text=summary_text,
        worked_seconds=worked_seconds,
        worked_text=worked_text,
        bootstrap_reply=bootstrap_reply,
    )

    state = load_state()
    state[ACTIVE_THREAD_KEY] = new_thread_id
    state[LAST_HANDOFF_KEY] = {
        "source_thread_id": source_thread_id,
        "new_thread_id": new_thread_id,
        "worked_seconds": worked_seconds,
        "worked_text": worked_text,
        "summary_file": str(summary_file),
        "metadata_file": str(metadata_file),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_state(state)
    upsert_env_value(ENV_FILE, "CODEX_FIXED_THREAD_ID", new_thread_id)

    telegram_message_ids: list[int] = []
    if not args.no_telegram:
        token = resolve_token(args.token)
        chat_id = resolve_chat_id(args.chat_id)
        client = TelegramBotClient(token)
        telegram_message_ids = send_handoff_telegram_message(
            client=client,
            chat_id=chat_id,
            source_thread_id=source_thread_id,
            new_thread_id=new_thread_id,
            worked_text=worked_text,
            summary_text=summary_text,
        )

    print(
        json.dumps(
            {
                "source_thread_id": source_thread_id,
                "new_thread_id": new_thread_id,
                "worked_seconds": worked_seconds,
                "worked_text": worked_text,
                "summary_file": str(summary_file),
                "metadata_file": str(metadata_file),
                "bootstrap_reply": bootstrap_reply,
                "telegram_message_ids": telegram_message_ids,
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
