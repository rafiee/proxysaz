"""Broadcast delivery: manual (send-now) and automatic (recurring) messages.

Both paths reuse `do_broadcast`, which walks the whole users table and sends
the given Telegram-HTML text, pacing itself so Telegram's flood limits aren't
tripped. A single `broadcast_sent` event is logged per run for the stats view.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from telegram.error import Forbidden, RetryAfter, TelegramError

from .database import async_session, BroadcastMessage, User, get_settings
from .stats import log_event

log = logging.getLogger("proxy-bot.broadcast")

# Keep the delivered-copy index only for the few most recent manual broadcasts,
# so the "edit last broadcast" feature works without the table growing forever.
_KEEP_BATCHES = 3


async def _next_batch_id():
    async with async_session() as s:
        cur = (await s.execute(select(func.max(BroadcastMessage.batch_id)))).scalar()
    return int(cur or 0) + 1


async def do_broadcast(bot, html_text, mode="manual", record=False):
    """Send `html_text` to every user. Returns (sent, failed).

    - Malformed HTML falls back to plain text so the message still goes out.
    - Users who blocked the bot (Forbidden) are counted as failed and skipped.
    - Honors Telegram's RetryAfter back-off.
    - When `record` is True, the (chat_id, message_id) of every delivered copy
      is stored under a fresh batch so the message can later be edited.
    """
    async with async_session() as s:
        user_ids = list((await s.execute(select(User.chat_id))).scalars().all())

    batch_id = await _next_batch_id() if record else None
    rows = []  # (chat_id, message_id) for this batch

    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            try:
                m = await bot.send_message(
                    uid, html_text, parse_mode="HTML", disable_web_page_preview=True
                )
            except TelegramError as e:
                # Likely bad HTML -> retry once as plain text.
                if isinstance(e, (Forbidden, RetryAfter)):
                    raise
                m = await bot.send_message(uid, html_text, disable_web_page_preview=True)
            sent += 1
            if record and m is not None:
                rows.append((uid, m.message_id))
        except RetryAfter as e:
            await asyncio.sleep(getattr(e, "retry_after", 2) + 1)
            try:
                m = await bot.send_message(uid, html_text, disable_web_page_preview=True)
                sent += 1
                if record and m is not None:
                    rows.append((uid, m.message_id))
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
        if record and rows:
            s.add_all([
                BroadcastMessage(batch_id=batch_id, chat_id=c, message_id=mid)
                for c, mid in rows
            ])
            await s.commit()
            # Prune old batches so the table stays small.
            keep = (await s.execute(
                select(BroadcastMessage.batch_id)
                .distinct().order_by(BroadcastMessage.batch_id.desc())
                .limit(_KEEP_BATCHES)
            )).scalars().all()
            if keep:
                await s.execute(
                    delete(BroadcastMessage).where(
                        BroadcastMessage.batch_id.notin_(list(keep))
                    )
                )
                await s.commit()
    log.info("Broadcast (%s): sent=%s failed=%s", mode, sent, failed)
    return sent, failed


async def edit_last_broadcast(bot, html_text):
    """Edit every delivered copy of the most recent MANUAL broadcast.

    Returns (edited, failed, found). `found` is False when there is nothing to
    edit (no recorded batch). Telegram only lets a bot edit its own messages
    for 48h, and copies that are unchanged/too-old simply count as failed.
    """
    async with async_session() as s:
        last = (await s.execute(select(func.max(BroadcastMessage.batch_id)))).scalar()
        if not last:
            return 0, 0, False
        rows = (await s.execute(
            select(BroadcastMessage.chat_id, BroadcastMessage.message_id)
            .where(BroadcastMessage.batch_id == last)
        )).all()

    edited = 0
    failed = 0
    for chat_id, message_id in rows:
        try:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=html_text,
                    parse_mode="HTML", disable_web_page_preview=True,
                )
            except TelegramError as e:
                if isinstance(e, RetryAfter):
                    raise
                # bad HTML -> retry as plain text
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=html_text,
                    disable_web_page_preview=True,
                )
            edited += 1
        except RetryAfter as e:
            await asyncio.sleep(getattr(e, "retry_after", 2) + 1)
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=html_text,
                    disable_web_page_preview=True,
                )
                edited += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    log.info("Edit last broadcast: edited=%s failed=%s", edited, failed)
    return edited, failed, True


async def push_menu_to_all(bot):
    """Push the up-to-date bottom menu to EVERY user by sending a short notice
    that carries the fresh ReplyKeyboardMarkup. This is the only way Telegram
    lets a bot refresh an already-visible reply keyboard — there is no API to
    silently swap it, a message must be sent. Admins get the admin menu, other
    users get the normal menu. Returns (sent, failed).
    """
    # Imported here to avoid a circular import at module load.
    from .config import ADMIN_IDS
    from .keyboards import admin_main_menu, user_main_menu

    async with async_session() as s:
        user_ids = list((await s.execute(select(User.chat_id))).scalars().all())

    admin_ids = set(int(a) for a in ADMIN_IDS)
    notice = "✨ منوی ربات به‌روز شد. دکمه‌های جدید اکنون در دسترس هستند."

    sent = 0
    failed = 0
    for uid in user_ids:
        kb = admin_main_menu() if int(uid) in admin_ids else user_main_menu()
        try:
            await bot.send_message(uid, notice, reply_markup=kb)
            sent += 1
        except RetryAfter as e:
            await asyncio.sleep(getattr(e, "retry_after", 2) + 1)
            try:
                await bot.send_message(uid, notice, reply_markup=kb)
                sent += 1
            except Exception:
                failed += 1
        except Forbidden:
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    log.info("Menu push: sent=%s failed=%s", sent, failed)
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
