# Workflow Remote Agent

Repo nay la bo recovery kit de dung lai nhanh setup Codex remote agent tren may moi hoac sau khi reset EC2.

No dong goi:

- Telegram bot CLI
- Telegram -> Codex bridge
- Codex handoff script
- `systemd` service de bridge tu chay lai sau reboot
- patch local cho `playwright-record-mcp`
- script cap nhat `~/.codex/config.toml`
- script verify sau cai dat

## Cau truc

- `assets/telegram-bot-cli/`: source dang chay cho Telegram bridge
- `patches/playwright-record-mcp.patch`: patch local cho MCP record video
- `scripts/install.sh`: script bootstrap chinh
- `scripts/verify_install.sh`: script kiem tra lai setup
- `docs/RESET_WITH_CODEX.md`: prompt/goi y de dua cho Codex sau khi reset may

## Quick Start

Clone repo:

```bash
git clone git@github.com:kietng04/workflow-remote-agent.git /home/ubuntu/workflow-remote-agent
cd /home/ubuntu/workflow-remote-agent
```

Chay bootstrap:

```bash
./scripts/install.sh
```

Neu day la may moi, script se:

- cai package he thong can thiet
- sync `telegram-bot-cli` vao `/home/ubuntu/telegram-bot-cli`
- tao `.env` tu template neu chua co
- clone/patch/build `~/.codex/mcp-servers/playwright-record-mcp`
- cap nhat `~/.codex/config.toml`
- cai `telegram-codex-bridge.service`
- tu dong `enable --now` service neu `.env` da du bien can thiet

## Cau hinh Telegram

Sau lan chay dau, sua file:

`/home/ubuntu/telegram-bot-cli/.env`

Can dien:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`
- `CODEX_FIXED_THREAD_ID`
- `CODEX_WORKDIR`

Mau co san o:

`assets/telegram-bot-cli/.env.example`

Sau khi sua `.env`, chay lai:

```bash
cd /home/ubuntu/workflow-remote-agent
./scripts/install.sh
```

## Xac thuc

Chay:

```bash
cd /home/ubuntu/workflow-remote-agent
./scripts/verify_install.sh
```

Script verify se kiem tra:

- `codex` binary ton tai
- Telegram CLI da duoc sync
- `systemd` service da cai
- service `telegram-codex-bridge.service` dang `active`
- MCP `playwright-record-mcp` da ton tai va build xong
- `~/.codex/config.toml` co block `playwright_record`
- `telegram_bot.py get-me` thanh cong neu token da duoc cau hinh

## Quan ly service

```bash
sudo systemctl status telegram-codex-bridge.service
sudo systemctl restart telegram-codex-bridge.service
sudo journalctl -u telegram-codex-bridge.service -n 50 --no-pager
```

Service da duoc `enable`, nen reboot EC2 xong no se tu chay lai.

## Luu y

- Khong commit file `.env` that.
- Khong commit `.telegram_bot_state.json`, `handoffs/`, `bridge.log`.
- `CODEX_FIXED_THREAD_ID` co the thay doi sau moi lan handoff, nen `.env` local moi la state that.
- Patch `playwright-record-mcp` duoc luu trong repo nay de may moi co the phuc hoi lai hieu ung cursor/type video.
