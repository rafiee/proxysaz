"""Broadcast delivery: manual (send-now) and automatic (recurring) messages.

Both paths reuse `do_broadcast`, which walks the whole users table and sends
the given Telegram-HTML text, pacing itself so Telegram's flood limits aren't
tripped. A single `broadcast_sent` event is logged per run for the stats view.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from telegram.error import Forbidden, RetryAfter, TelegramError

from .database import async_session, User, get_settings
from .stats import log_event

log = logging.getLogger("proxy-bot.broadcast")


async def do_broadcast(bot, html_text, mode="manual"):
    """Send `html_text` to every user. Returns (sent, failed).

    - Malformed HTML falls back to plain text so the message still goes out.
    - Users who blocked the bot (Forbidden) are counted as failed and skipped.
    - Honors Telegram's RetryAfter back-off.
    """
    async with async_session() as s:
        user_ids = list((await s.execute(select(User.chat_id))).scalars().all())

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            try:
                await bot.send_message(
                    uid, html_text, parse_mode="HTML", disable_web_page_preview=True
                )
            except TelegramError as e:
                # Likely bad HTML -> retry once as plain text.
                if isinstance(e, (Forbidden, RetryAfter)):
                    raise
                await bot.send_message(uid, html_text, disable_web_page_preview=True)
            sent += 1
        except RetryAfter as e:
            await asyncio.sleep(getattr(e, "retry_after", 2) + 1)
            try:
                await bot.send_message(uid, html_text, disable_web_page_preview=True)
                sent += 1
            except Exception:
                failed += 1
        except Forbidden:
            failed += 1  # user blocked the bot
        except Exception:
            failed += 1
        # Gentle pacing: ~20 msgs/sec is safe below Telegram's 30/sec cap.
        await asyncio.sleep(0.05)

    async with async_session() as s:
        await log_event(s, "broadcast_sent", ref=mode)
    log.info("Broadcast (%s): sent=%s failed=%s", mode, sent, failed)
    return sent, failed


async def auto_broadcast_tick(context):
    """JobQueue callback: run the automatic broadcast if it is enabled and due.

    Scheduled hourly; it self-gates on `broadcast_auto_hours` and the last
    send time so the interval (12h / 24h / 48h / ...) is honored regardless of
    how often the tick fires.
    """
    async with async_session() as s:
        st = await get_settings(s)
        if not getattr(st, "broadcast_auto_enabled", False):
            return
        text = (st.broadcast_auto_message or "").strip()
        if not text:
            return
        hours = int(getattr(st, "broadcast_auto_hours", 24) or 24)
        last = st.broadcast_last_sent_at
        now = datetime.utcnow()
        due = last is None or (now - last) >= timedelta(hours=hours)
        if not due:
            return
        # Mark as sent BEFORE sending so a long run can't double-fire.
        st.broadcast_last_sent_at = now
        await s.commit()

    sent, failed = await do_broadcast(context.bot, text, mode="auto")
    log.info("Auto broadcast done: sent=%s failed=%s", sent, failed)
