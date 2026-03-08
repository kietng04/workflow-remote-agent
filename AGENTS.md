# AGENTS.md

## Language
All user-facing responses must be in Vietnamese unless the user explicitly requests another language.

## Mission
This repository is the source of truth for rebuilding the remote Codex + Telegram bridge setup on a fresh machine.
When asked to restore or bootstrap the environment, prefer reusing the scripts in this repo instead of recreating setup steps manually.

## Operating Rules
1. Treat this repo as the canonical recovery kit.
2. Never commit real secrets such as Telegram bot tokens or live `.env` files.
3. Prefer running `scripts/install.sh` for setup and `scripts/verify_install.sh` for validation.
4. If the Telegram bridge is part of the task, verify both the installed files and the `systemd` service status.
5. If Playwright Record MCP is part of the task, ensure the patch is applied and the MCP build succeeds.

## Expected Workflow
1. Read `README.md`.
2. Run `scripts/install.sh`.
3. Fill `/home/ubuntu/telegram-bot-cli/.env` from the template if secrets are needed.
4. Re-run `scripts/install.sh` if `.env` changed.
5. Run `scripts/verify_install.sh`.
6. Only then report completion.
