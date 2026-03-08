# Telegram Bot CLI

CLI Python thuần để:

- kiểm tra bot token
- lấy `chat_id` từ `getUpdates`
- ghi nhớ `chat_id` mặc định
- gửi tin nhắn vào Telegram
- chờ người dùng gửi `/start` rồi gửi tin nhắn ngay
- poll Telegram và resume một `Codex thread_id` cố định
- handoff một `Codex thread_id` sang thread mới với summary tự động

## Vị trí

Project này nằm ngoài `clinic-projects`:

`/home/ubuntu/telegram-bot-cli`

## Cấu hình

1. Tạo file `.env` từ `.env.example`
2. Điền `TELEGRAM_BOT_TOKEN`

## Lệnh chính

```bash
python3 telegram_bot.py get-me
python3 telegram_bot.py get-updates
python3 telegram_bot.py list-chats
python3 telegram_bot.py wait-chat --timeout 180
python3 telegram_bot.py send --chat-id <CHAT_ID> --text "Xin chao"
python3 telegram_bot.py send-file --chat-id <CHAT_ID> --path /path/to/file.webm --as video --caption "YouTube record"
python3 telegram_bot.py wait-and-send --text "Xin chao tu bot" --timeout 180
./send_telegram.sh "Xin chao nhanh"
./send_telegram.sh --wait "Gui ngay sau khi user bam /start"
./start_codex_bridge.sh
python3 codex_handoff.py
```

## Ghi chú

- Bot không thể chủ động nhắn cho một user nếu user chưa mở chat và gửi `/start`.
- Sau khi có `chat_id`, CLI sẽ lưu vào `.telegram_bot_state.json` để dùng lại.
- Khi dùng `send-file --as video`, CLI sẽ tự convert file không phải `mp4` sang `mp4` trước khi gửi Telegram.
- Bridge khi gửi reply text sẽ tự đính thêm dòng `Worked for X minutes Y seconds` dựa trên thời điểm thread active được tạo.

## Bridge Telegram -> Codex

Bridge hiện chạy theo mode single-user:

- chỉ nhận `TELEGRAM_ALLOWED_CHAT_ID`
- resume thread active lưu trong `.telegram_bot_state.json`, fallback về `CODEX_FIXED_THREAD_ID`
- dùng `codex exec resume ... --dangerously-bypass-approvals-and-sandbox`

Chạy foreground:

```bash
cd /home/ubuntu/telegram-bot-cli
./start_codex_bridge.sh
```

Chạy background:

```bash
cd /home/ubuntu/telegram-bot-cli
nohup ./start_codex_bridge.sh > bridge.log 2>&1 &
```

Chạy tự động cùng hệ thống bằng `systemd`:

```bash
sudo systemctl enable --now telegram-codex-bridge.service
sudo systemctl status telegram-codex-bridge.service
sudo journalctl -u telegram-codex-bridge.service -n 50 --no-pager
```

Replay một update cũ để test:

```bash
cd /home/ubuntu/telegram-bot-cli
./start_codex_bridge.sh --once --offset 809128413
```

## Handoff thread Codex

Script `codex_handoff.py` sẽ:

- resume thread active hiện tại để yêu cầu Codex tự tóm tắt handoff
- tạo một thread mới bằng `codex exec --json --dangerously-bypass-approvals-and-sandbox`
- ghi `thread_id` mới vào `.telegram_bot_state.json`
- cập nhật `CODEX_FIXED_THREAD_ID` trong `.env`
- lưu summary + metadata vào thư mục `handoffs/`
- gửi thông báo sang Telegram kèm `Worked for X minutes Y seconds`

Chạy:

```bash
cd /home/ubuntu/telegram-bot-cli
python3 codex_handoff.py
```

Chỉ in kết quả local, không gửi Telegram:

```bash
cd /home/ubuntu/telegram-bot-cli
python3 codex_handoff.py --no-telegram
```
