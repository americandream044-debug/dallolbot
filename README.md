# Dasturlash & AI Control Bot

Private admin command center for the Uzbek Telegram channel **Dasturlash & AI** (`@dasturlash_ai`). Built with Python 3.11+, aiogram 3.x, SQLite/WAL, APScheduler, and OpenAI/Anthropic provider adapters.

> Security note: users must open the bot with `/start` before Telegram allows the bot to message them. Broadcast targets only users who have interacted with the bot; blocked accounts are recorded and excluded from later broadcasts. Keep `.env`, database backups, and logs private.

## Included

- Public `/start`, `/help`, mandatory-channel subscription gate, and admin support tickets with text/photo/voice/document/video.
- Admin-only prompt generator/library, AI channel-post variants, HTML cleanup, styles/fonts, drafts, one-off and recurring scheduling, daily queue.
- Ticket inbox, tags/status/star/ban, AI reply draft, broadcast audience segments and cancel button.
- User search and notes, analytics dashboard, event/source reports, manual views input, CSV exports, weekly report, reaction snapshots.
- Runtime settings, backup/cleanup/audit/health/referral tools, daily SQLite backup, error reporting, and neon terminal UI.

The Telegram Bot API does not expose channel post view counts to bots. The analytics dashboard therefore never invents views; an admin may enter a view count manually to calculate a reactions-based engagement estimate.

---

# O‘zbekcha qo‘llanma

## 1. Talablar

- Python 3.11 yoki undan yangi versiya.
- Telegram bot tokeni (`@BotFather`).
- `@dasturlash_ai` kanalida administrator huquqiga ega bot.
- OpenAI yoki Anthropic API kaliti.

## 2. BotFather orqali bot ochish

1. Telegram’da `@BotFather` ni oching va `/newbot` yuboring.
2. Bot nomi va username tanlang.
3. Berilgan tokenni maxfiy saqlang. Uni hech kimga, shu jumladan GitHub yoki kanalga yubormang.
4. Botni `@dasturlash_ai` kanaliga administrator qilib qo‘shing.
5. Quyidagi ruxsatlarni yoqing: **Post messages**, **Edit messages**, **Delete messages**. Obunani tekshirish va join/leave eventlari uchun bot kanalda admin bo‘lib qolishi kerak.

## 3. CHANNEL_ID olish

- `CHANNEL_USERNAME=dasturlash_ai` qiymati public username bo‘ladi (`@` belgisiz).
- `CHANNEL_ID` odatda `-100...` bilan boshlanadigan raqamli kanal ID. Uni o‘zingiz boshqaradigan Telegram bot/API update logidan yoki ishonchli Telegram admin vositasidan aniqlang.
- Botni kanalga qo‘shgandan keyin ham `CHANNEL_ID` va username bir kanalga tegishli ekanini tekshiring.

## 4. Lokal ishga tushirish

```bash
# 1) Loyihani yuklab/ko‘chirib, papkaga kiring
cd dasturlash_ai_bot

# 2) Virtual muhit
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.venv\\Scripts\\Activate.ps1

# 3) Kutubxonalar
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4) Muhit fayli
cp .env.example .env
# Windows: copy .env.example .env
# .env faylini tahrir qilib BOT_TOKEN, ADMIN_IDS, CHANNEL_ID va AI_API_KEY kiriting.

# 5) Ishga tushirish
python -m bot.main
```

`ADMIN_IDS` ga o‘zingizning raqamli Telegram user ID’ingizni yozing. Bir nechta admin bo‘lsa, vergul bilan ajrating. `BACKUP_CHAT_ID` bo‘sh qolsa, birinchi admin ID ishlatiladi.

AI sozlamalari:

```env
AI_PROVIDER=openai
AI_API_KEY=your_private_api_key
AI_MODEL=gpt-4.1-mini
```

Anthropic ishlatish uchun `AI_PROVIDER=anthropic` va hisobingizda mavjud model nomini belgilang.

## 5. Birinchi ishga tushirish tekshiruvi

Bot kanalga kirish va post/edit/delete huquqlarini tekshiradi. Xato chiqsa:

1. Bot kanal administratorlari ro‘yxatida ekanini tekshiring.
2. `Post messages`, `Edit messages`, `Delete messages` ruxsatlarini yoqing.
3. `.env` dagi `CHANNEL_ID` va `CHANNEL_USERNAME` ni qayta tekshiring.
4. Admin shaxsiy chatida botga `/start` yuborgan bo‘lishi kerak.

Admin panel: `/admin`. Ommaviy foydalanuvchilar uchun faqat `/start`, `/help` va murojaat tugmasi mavjud.

## 6. VPS + systemd

Quyidagi misol Ubuntu VPS uchun:

```bash
sudo mkdir -p /opt/dasturlash_ai_bot
sudo chown -R "$USER":"$USER" /opt/dasturlash_ai_bot
# Loyiha fayllarini /opt/dasturlash_ai_bot ichiga ko‘chiring.
cd /opt/dasturlash_ai_bot
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env
sudo useradd --system --home /opt/dasturlash_ai_bot --shell /usr/sbin/nologin botuser || true
sudo chown -R botuser:botuser /opt/dasturlash_ai_bot
sudo cp deploy/dasturlash-ai-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dasturlash-ai-bot
sudo systemctl status dasturlash-ai-bot
```

Loglarni ko‘rish:

```bash
sudo journalctl -u dasturlash-ai-bot -f
```

`.env` fayli faqat `botuser` va root tomonidan o‘qiladigan bo‘lsin:

```bash
sudo chmod 600 /opt/dasturlash_ai_bot/.env
```

## 7. Docker orqali deploy

```bash
cp .env.example .env
nano .env
docker compose up -d --build
docker compose logs -f
docker compose ps
```

SQLite ma’lumotlari `./data`, loglar `./logs` papkasida saqlanadi. Konteyner qayta ishga tushsa, rejalashtirilgan postlar DB’dan tiklanadi.

## 8. Asosiy sozlamalar

- `TIMEZONE=Asia/Tashkent`: barcha reja va hisobot vaqtlari.
- `SUPPORT_COOLDOWN=30`: dastlabki anti-spam intervali; admin paneldan o‘zgartirish mumkin.
- `MAX_MESSAGE_LENGTH=3500`: support matni chegarasi.
- Admin panel → **Sozlamalar**: majburiy obuna, effektlar, avto-reaksiya, haftalik hisobot, AI limit, anti-spam va welcome matni.
- Admin panel → **Asboblar**: backup, cleanup, audit, health check va referral link.

---

# English setup guide

## Requirements

- Python 3.11+.
- A Telegram bot token from `@BotFather`.
- The bot must be an administrator in `@dasturlash_ai` with Post, Edit, and Delete Messages permissions.
- An OpenAI or Anthropic API key.

## Setup

1. Create a bot with `/newbot` in `@BotFather` and keep the token private.
2. Add the bot as an administrator to `@dasturlash_ai`; enable **Post messages**, **Edit messages**, and **Delete messages**.
3. Copy `.env.example` to `.env`.
4. Set `BOT_TOKEN`, numeric `ADMIN_IDS`, the channel's numeric `CHANNEL_ID`, `CHANNEL_USERNAME`, `AI_PROVIDER`, `AI_API_KEY`, and `AI_MODEL`.
5. Install and run:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m bot.main
```

For a public channel use `CHANNEL_USERNAME=dasturlash_ai` (without `@`). `CHANNEL_ID` is the numeric channel id, normally beginning with `-100`. `BACKUP_CHAT_ID` is optional; it defaults to the first admin ID.

## systemd deployment

Copy the project to `/opt/dasturlash_ai_bot`, create the virtual environment, install requirements, configure `.env`, then install `deploy/dasturlash-ai-bot.service` into `/etc/systemd/system/`. Run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dasturlash-ai-bot
sudo journalctl -u dasturlash-ai-bot -f
```

## Docker deployment

```bash
cp .env.example .env
# Fill in .env before starting.
docker compose up -d --build
docker compose logs -f
```

The database and rotating logs are mounted into local `data/` and `logs/` directories. Do not publish `.env`, tokens, API keys, database files, or backups.

## Operational notes

- A Telegram bot cannot initiate a private conversation with a user who has not started the bot. Broadcasts use the bot's own user table and skip banned users; Telegram-blocked users are marked `is_blocked`.
- Channel view counts are not available through the Telegram Bot API. The admin may enter a view count manually; reaction counts are stored from reaction-count updates.
- Scheduled posts are persisted in SQLite and restored on restart. Scheduler jobs run in the configured timezone.
- The provider adapter performs up to three attempts with exponential backoff and a 50-second overall request timeout.
