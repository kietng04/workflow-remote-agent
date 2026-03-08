# Reset With Codex

Neu reset may va muon Codex dung lai setup tu repo nay, co the dua prompt ngan gon sau:

```text
Clone git@github.com:kietng04/workflow-remote-agent.git vao /home/ubuntu/workflow-remote-agent.
Doc README.md va AGENTS.md trong repo.
Chay ./scripts/install.sh.
Neu /home/ubuntu/telegram-bot-cli/.env chua co gia tri that, tao tu template va dien cac bien:
TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHAT_ID, CODEX_FIXED_THREAD_ID, CODEX_WORKDIR.
Sau do chay lai ./scripts/install.sh.
Chay ./scripts/verify_install.sh.
Neu bridge da cau hinh day du, xac nhan telegram-codex-bridge.service dang active va co the gui test message qua Telegram.
Xac nhan bridge dang ap dung rule: task demonstrable phai quay proof video va gui Telegram truoc khi bao DONE.
Xac nhan dong Worked for duoc tinh theo tung message Telegram, khong theo tuoi cua thread.
Tra loi bang tieng Viet.
```

Neu muon Codex chi verify lai setup da co san:

```text
Trong repo /home/ubuntu/workflow-remote-agent, chay ./scripts/verify_install.sh va bao cao ket qua bang tieng Viet.
Neu co thanh phan nao thieu thi dung lai bang cac script co san trong repo, khong setup tay tung buoc neu co the tranh duoc.
```
