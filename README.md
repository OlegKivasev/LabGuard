# vpn-bot

MVP Telegram bot for free VPN onboarding.

## Quick start

1. Create and activate virtual environment.
2. Install dependencies:
   - `python -m pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill values.
4. Validate config:
   - `py bot.py --check-config`
5. Start bot:
   - `py bot.py`

On startup, the bot creates SQLite tables automatically if they do not exist.

## Current scope (before Marzban API integration)

- `/start` registers user and logs event.
- `/get` activates local 14-day trial timer in SQLite.
- `/status` shows local trial status.
- `/help` and `/apps` return setup instructions.
- `/support <text>` creates a local support ticket.
- Reminder scheduler runs every 6 hours and sends 3d/1d messages based on local expiry.

## Smoke test

- `py -m scripts.smoke_pre_api`

## Telegram integration (without Marzban API)

1. Create bot in BotFather and get `BOT_TOKEN`.
2. Create `.env` from `.env.example` and fill `BOT_TOKEN`.
3. Check config: `py bot.py --check-config`.
4. Check Telegram API: `py bot.py --check-telegram`.
5. Run bot: `py bot.py`.
6. In Telegram test commands in order: `/start`, `/get`, `/status`, `/help`, `/apps`, `/support test`.

On startup bot registers command menu in Telegram automatically.

If Marzban uses a self-signed certificate, set `MARZBAN_VERIFY_TLS=false` temporarily.

Admin commands (IDs from `ADMIN_TELEGRAM_IDS`):
- `/admin_app`
- `/admin_users [limit]`
- `/admin_deactivate <telegram_id>`
- `/admin_delete <telegram_id>`

`ADMIN_TELEGRAM_IDS` accepts Telegram numeric IDs and/or usernames (e.g. `123456789,@myuser`).

Mini App settings:
- `WEB_APP_BASE_URL` (public URL, e.g. `https://bot.example.com`)
- `WEB_APP_HOST` (default `0.0.0.0`)
- `WEB_APP_PORT` (default `8081`)
- `WEB_APP_TOKEN_TTL_MINUTES` (default `30`)
