#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import re


def upsert_block(content: str, header: str, block: str) -> str:
    pattern = re.compile(rf"(?ms)^\[{re.escape(header)}\]\n.*?(?=^\[|\Z)")
    replacement = block.strip() + "\n\n"
    if pattern.search(content):
        return pattern.sub(replacement, content, count=1).rstrip() + "\n"
    if content and not content.endswith("\n"):
        content += "\n"
    if content.strip():
        content = content.rstrip() + "\n\n"
    return content + replacement


def main() -> None:
    parser = argparse.ArgumentParser(description="Cap nhat block MCP trong ~/.codex/config.toml")
    parser.add_argument("--config", required=True, help="Duong dan config.toml")
    parser.add_argument("--playwright-record-dir", required=True, help="Thu muc repo playwright-record-mcp")
    args = parser.parse_args()

    config_path = Path(args.config).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    content = config_path.read_text(encoding="utf-8") if config_path.exists() else ""

    record_dir = Path(args.playwright_record_dir).expanduser()
    video_dir = Path.home() / ".codex" / "playwright-recordings"

    playwright_block = """[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest"]"""

    record_block = f"""[mcp_servers.playwright_record]
command = "node"
args = [
  "{record_dir / 'cli.js'}",
  "--headless",
  "--record-video",
  "--video-dir",
  "{video_dir}",
]"""

    updated = upsert_block(content, "mcp_servers.playwright", playwright_block)
    updated = upsert_block(updated, "mcp_servers.playwright_record", record_block)

    config_path.write_text(updated.rstrip() + "\n", encoding="utf-8")
    print(f"Updated {config_path}")


if __name__ == "__main__":
    main()
