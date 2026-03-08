#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / ".telegram_bot_state.json"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fail(message: str, exit_code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)


def ensure_mp4_video(file_path: Path) -> tuple[Path, Path | None]:
    source = file_path.expanduser().resolve()
    if source.suffix.lower() == ".mp4":
        return source, None

    converted_dir = BASE_DIR / "converted_videos"
    converted_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = converted_dir / f"{source.stem}-{stamp}.mp4"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        str(target),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0 or not target.exists():
        details = completed.stderr.strip() or completed.stdout.strip() or "ffmpeg convert failed"
        fail(f"Khong convert duoc video sang mp4: {details}")
    return target, target


class TelegramBotClient:
    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}/"

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        encoded = urllib.parse.urlencode(params or {}).encode("utf-8")
        request = urllib.request.Request(self.base_url + method, data=encoded)
        try:
            with urllib.request.urlopen(request, timeout=65) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            fail(f"Telegram API HTTP {exc.code}: {body}")
        except urllib.error.URLError as exc:
            fail(f"Network error: {exc}")

        if not payload.get("ok"):
            fail(f"Telegram API error: {payload}")
        return payload

    def get_me(self) -> dict[str, Any]:
        return self.request("getMe")["result"]

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 0,
        allowed_updates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        if allowed_updates:
            params["allowed_updates"] = json.dumps(allowed_updates)
        return self.request("getUpdates", params)["result"]

    def send_message(
        self,
        *,
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_notification": str(disable_notification).lower(),
        }
        if parse_mode:
            params["parse_mode"] = parse_mode
        return self.request("sendMessage", params)["result"]

    def send_file(
        self,
        *,
        chat_id: int | str,
        file_path: str,
        media_kind: str = "document",
        caption: str | None = None,
        disable_notification: bool = False,
    ) -> dict[str, Any]:
        file_path_obj = Path(file_path).expanduser().resolve()
        if not file_path_obj.exists():
            fail(f"Khong tim thay file: {file_path_obj}")

        upload_path = file_path_obj
        cleanup_path: Path | None = None
        if media_kind == "video":
            upload_path, cleanup_path = ensure_mp4_video(file_path_obj)

        url = self.base_url + ("sendVideo" if media_kind == "video" else "sendDocument")
        command = [
            "curl",
            "-sS",
            "-X",
            "POST",
            "-F",
            f"chat_id={chat_id}",
            "-F",
            f"disable_notification={'true' if disable_notification else 'false'}",
        ]
        if caption:
            command.extend(["-F", f"caption={caption}"])

        mime_type = mimetypes.guess_type(str(upload_path))[0] or "application/octet-stream"
        command.extend(
            [
                "-F",
                f"{media_kind}=@{upload_path};type={mime_type}",
                url,
            ]
        )

        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True)
            if completed.returncode != 0:
                fail(f"curl upload failed: {completed.stderr.strip() or completed.stdout.strip()}")
            try:
                payload = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                fail(f"Khong parse duoc phan hoi Telegram: {exc}: {completed.stdout[:500]}")
            if not payload.get("ok"):
                fail(f"Telegram API error: {payload}")
            return payload["result"]
        finally:
            if cleanup_path and cleanup_path.exists():
                cleanup_path.unlink()


def extract_chat(update: dict[str, Any]) -> dict[str, Any] | None:
    direct_sources = [
        update.get("message"),
        update.get("edited_message"),
        update.get("channel_post"),
        update.get("edited_channel_post"),
        update.get("my_chat_member"),
        update.get("chat_member"),
    ]
    for source in direct_sources:
        if isinstance(source, dict) and isinstance(source.get("chat"), dict):
            return source["chat"]

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        message = callback.get("message")
        if isinstance(message, dict) and isinstance(message.get("chat"), dict):
            return message["chat"]

    return None


def chat_label(chat: dict[str, Any]) -> str:
    title = chat.get("title")
    if title:
        return title

    first_name = chat.get("first_name")
    last_name = chat.get("last_name")
    username = chat.get("username")
    full_name = " ".join(part for part in [first_name, last_name] if part)
    if full_name:
        return full_name
    if username:
        return f"@{username}"
    return str(chat.get("id"))


def summarize_chats(updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: dict[int, dict[str, Any]] = {}
    for update in updates:
        chat = extract_chat(update)
        if not chat or "id" not in chat:
            continue
        summaries[int(chat["id"])] = {
            "chat_id": int(chat["id"]),
            "type": chat.get("type", "unknown"),
            "label": chat_label(chat),
            "username": chat.get("username"),
            "last_update_id": update.get("update_id"),
        }

    return sorted(summaries.values(), key=lambda item: (item["type"], item["chat_id"]))


def choose_chat_id(args: argparse.Namespace, state: dict[str, Any], updates: list[dict[str, Any]]) -> int:
    if args.chat_id is not None:
        return int(args.chat_id)
    saved = state.get("default_chat_id")
    if saved is not None:
        return int(saved)

    chats = summarize_chats(updates)
    if len(chats) == 1:
        return int(chats[0]["chat_id"])

    if not chats:
        fail(
            "Chua tim thay chat nao cho bot. Hay mo t.me/codexsgu_bot va gui /start, "
            "sau do chay lai lenh send hoac wait-and-send."
        )

    fail(
        "Co nhieu chat kha dung. Hay chi dinh --chat-id hoac chay list-chats de chon chat phu hop."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="CLI nho gon de kiem tra va gui tin nhan qua Telegram Bot API."
    )
    parser.add_argument(
        "--token",
        help="Telegram bot token. Mac dinh doc tu TELEGRAM_BOT_TOKEN trong .env.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("get-me", help="Kiem tra token va in thong tin bot.")

    parser_updates = subparsers.add_parser("get-updates", help="Doc update thô tu Telegram.")
    parser_updates.add_argument("--offset", type=int, help="Offset cho getUpdates.")
    parser_updates.add_argument("--timeout", type=int, default=0, help="Long poll timeout (giay).")

    parser_list = subparsers.add_parser("list-chats", help="Rut ra cac chat_id co san tu updates.")
    parser_list.add_argument("--timeout", type=int, default=0, help="Long poll timeout (giay).")

    parser_set = subparsers.add_parser("set-default-chat", help="Luu chat_id mac dinh vao state local.")
    parser_set.add_argument("chat_id", type=int)

    parser_send = subparsers.add_parser("send", help="Gui tin nhan den chat da chon.")
    parser_send.add_argument("--chat-id", type=int, help="Chat ID dich.")
    parser_send.add_argument("--text", required=True, help="Noi dung tin nhan.")
    parser_send.add_argument(
        "--parse-mode",
        choices=["HTML", "MarkdownV2"],
        help="Che do parse cua Telegram.",
    )
    parser_send.add_argument(
        "--disable-notification",
        action="store_true",
        help="Gui im lang.",
    )

    parser_wait = subparsers.add_parser(
        "wait-chat",
        help="Cho toi khi bot nhan duoc mot update co chat_id, roi luu chat mac dinh.",
    )
    parser_wait.add_argument("--timeout", type=int, default=120, help="Tong thoi gian cho (giay).")
    parser_wait.add_argument(
        "--poll-timeout",
        type=int,
        default=30,
        help="Gia tri timeout moi lan goi getUpdates (giay).",
    )

    parser_wait_send = subparsers.add_parser(
        "wait-and-send",
        help="Cho chat moi roi gui tin nhan ngay lap tuc.",
    )
    parser_wait_send.add_argument("--text", required=True, help="Noi dung tin nhan.")
    parser_wait_send.add_argument("--timeout", type=int, default=180, help="Tong thoi gian cho (giay).")
    parser_wait_send.add_argument(
        "--poll-timeout",
        type=int,
        default=30,
        help="Gia tri timeout moi lan goi getUpdates (giay).",
    )
    parser_wait_send.add_argument(
        "--parse-mode",
        choices=["HTML", "MarkdownV2"],
        help="Che do parse cua Telegram.",
    )

    parser_send_file = subparsers.add_parser("send-file", help="Gui file hoac video den Telegram.")
    parser_send_file.add_argument("--chat-id", type=int, help="Chat ID dich.")
    parser_send_file.add_argument("--path", required=True, help="Duong dan file can gui.")
    parser_send_file.add_argument(
        "--as",
        dest="media_kind",
        choices=["document", "video"],
        default="document",
        help="Gui file theo kieu document hoac video.",
    )
    parser_send_file.add_argument("--caption", help="Caption tu chon.")
    parser_send_file.add_argument(
        "--disable-notification",
        action="store_true",
        help="Gui im lang.",
    )

    return parser


def resolve_token(cli_token: str | None) -> str:
    load_env_file(ENV_FILE)
    token = cli_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        fail(
            f"Khong tim thay token. Hay tao {ENV_FILE} voi TELEGRAM_BOT_TOKEN=... "
            "hoac truyen --token."
        )
    return token


def wait_for_chat(
    client: TelegramBotClient,
    *,
    state: dict[str, Any],
    total_timeout: int,
    poll_timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.time() + total_timeout
    offset = state.get("last_update_id")
    if offset is not None:
        offset = int(offset) + 1

    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        updates = client.get_updates(
            offset=offset,
            timeout=min(poll_timeout, remaining),
        )
        if not updates:
            continue

        last_update_id = int(updates[-1]["update_id"])
        state["last_update_id"] = last_update_id
        save_state(state)
        offset = last_update_id + 1

        chats = summarize_chats(updates)
        if chats:
            chosen = chats[0]
            state["default_chat_id"] = chosen["chat_id"]
            save_state(state)
            return chosen, state

    fail("Het thoi gian cho update moi. Hay gui /start cho bot roi chay lai.")
    raise AssertionError("unreachable")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    token = resolve_token(args.token)
    client = TelegramBotClient(token)
    state = load_state()

    if args.command == "get-me":
        print(json.dumps(client.get_me(), ensure_ascii=True, indent=2))
        return

    if args.command == "get-updates":
        updates = client.get_updates(offset=args.offset, timeout=args.timeout)
        print(json.dumps(updates, ensure_ascii=True, indent=2))
        return

    if args.command == "list-chats":
        offset = state.get("last_update_id")
        if offset is not None:
            offset = int(offset) + 1
        updates = client.get_updates(offset=offset, timeout=args.timeout)
        if updates:
            state["last_update_id"] = int(updates[-1]["update_id"])
            save_state(state)
        chats = summarize_chats(updates)
        print(json.dumps(chats, ensure_ascii=True, indent=2))
        if not chats:
            print(
                "Khong co chat nao trong updates. Hay mo bot va gui /start truoc.",
                file=sys.stderr,
            )
        return

    if args.command == "set-default-chat":
        state["default_chat_id"] = int(args.chat_id)
        save_state(state)
        print(json.dumps({"default_chat_id": state["default_chat_id"]}, ensure_ascii=True, indent=2))
        return

    if args.command == "wait-chat":
        chat, _ = wait_for_chat(
            client,
            state=state,
            total_timeout=args.timeout,
            poll_timeout=args.poll_timeout,
        )
        print(json.dumps(chat, ensure_ascii=True, indent=2))
        return

    if args.command == "wait-and-send":
        chat, state = wait_for_chat(
            client,
            state=state,
            total_timeout=args.timeout,
            poll_timeout=args.poll_timeout,
        )
        message = client.send_message(
            chat_id=chat["chat_id"],
            text=args.text,
            parse_mode=args.parse_mode,
        )
        state["default_chat_id"] = int(chat["chat_id"])
        save_state(state)
        print(json.dumps(message, ensure_ascii=True, indent=2))
        return

    if args.command == "send":
        updates = client.get_updates(timeout=0)
        if updates:
            state["last_update_id"] = int(updates[-1]["update_id"])
            save_state(state)
        chat_id = choose_chat_id(args, state, updates)
        message = client.send_message(
            chat_id=chat_id,
            text=args.text,
            parse_mode=args.parse_mode,
            disable_notification=args.disable_notification,
        )
        state["default_chat_id"] = int(chat_id)
        save_state(state)
        print(json.dumps(message, ensure_ascii=True, indent=2))
        return

    if args.command == "send-file":
        updates = client.get_updates(timeout=0)
        if updates:
            state["last_update_id"] = int(updates[-1]["update_id"])
            save_state(state)
        chat_id = choose_chat_id(args, state, updates)
        message = client.send_file(
            chat_id=chat_id,
            file_path=args.path,
            media_kind=args.media_kind,
            caption=args.caption,
            disable_notification=args.disable_notification,
        )
        state["default_chat_id"] = int(chat_id)
        save_state(state)
        print(json.dumps(message, ensure_ascii=True, indent=2))
        return

    parser.error("Lenh khong hop le.")


if __name__ == "__main__":
    main()
