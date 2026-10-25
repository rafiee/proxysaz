# Telegram Free-Proxy Bot

Distributes free Telegram proxies (MTProto / SOCKS). Users get a single
**Get proxy -> Connect** flow; admins inject, name, and manage proxies, choose
the selection strategy, control rotation, and set forced-join channels.

UI language: **Persian**. Code/comments: English.

## Environment variables

| Var | Meaning |
|-----|---------|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `ADMIN_CHAT_IDS` | Comma-separated numeric Telegram user IDs (admins) |
| `DATABASE_URL` | Neon Postgres URL (any Neon format; auto-normalized for asyncpg) |

## Run locally

```bash
pip install -r requirements.txt
export BOT_TOKEN=... ADMIN_CHAT_IDS=... DATABASE_URL=...
python main.py
```

## Deploy (Northflank + Neon)

1. Push to GitHub (auto-deploy configured).
2. In Northflank service -> Environment, add `BOT_TOKEN`, `ADMIN_CHAT_IDS`,
   `DATABASE_URL` (see below).
3. Northflank builds the Dockerfile and runs `python main.py`.
4. Tables are auto-created on first start.

## Features

- **User:** one button -> join-gate (if channels required) -> Connect URL button.
- **Admin:** add proxy (paste one link, then name it), list/enable/disable/pin/delete,
  selection strategy (single / newest / spread-equally by least-served, no random),
  rotation (manual or automatic every N hours), forced-join channels on/off, stats.
