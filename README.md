# LabelBot

A Telegram bot for label submission with a crypto top-up balance system.

## Features

**Users:**
- `/start` — shows main menu (Submit Label / Top Up / Balance)
- **Top Up** — choose BTC, ETH, or USDT (TRC20), enter amount, paste TX hash → admin reviews and approves
- **Submit Label** — send a label image, $18 deducted from balance automatically
- **My Balance** — check current balance

**Admin (`@wsboxing`):**
- Instantly pinged when a new label is submitted (with the image)
- Instantly pinged when a new deposit request comes in
- `/admin` — overview panel
- `/labels` — view all submitted labels + images
- `/deposits` — list pending deposit requests
- `/approve <id>` — approve a deposit (credits user balance + notifies them)
- `/reject <id>` — reject a deposit (notifies user)
- `/allusers` — list all users and balances
- `/addbalance <user_id> <amount>` — manually credit a user

## Setup

1. **Create a bot** via [@BotFather](https://t.me/BotFather) and copy the token.

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # edit .env and fill in BOT_TOKEN + your wallet addresses
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run:**
   ```bash
   python bot.py
   ```

5. **Admin setup:** Have `@wsboxing` send `/start` to the bot once so the bot learns their chat ID — after that, pings will work automatically.

## Notes

- Database is stored in `labelbot.db` (SQLite, auto-created on first run).
- Deposits are manually verified — the admin checks the TX hash and runs `/approve <id>`.
- Label cost is hardcoded to $18 in `bot.py` (`LABEL_COST`).
- Only wallets with a non-empty address in `.env` appear as payment options.
