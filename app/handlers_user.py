"""User-facing handlers: /start, 'Get proxy' flow, forced-join gate."""
from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, User, Proxy, Channel, get_settings
from .keyboards import (
    user_main_menu, admin_main_menu, connect_button, join_channels_kb,
    proxy_delivery_kb, broken_report_kb, promo_channels_kb,
)
from .membership import (
    missing_channels, gate_channels, optional_channels, unjoined_optional_channels,
)
from .rotation import pick_proxy, mark_served, pick_promo_channels
from .stats import log_event, bump_channel_stat
from .channel_promo import render_join_gate, render_promo

GET_PROXY_TEXT = "🚀 دریافت پروکسی"


def is_admin(chat_id: int) -> bool:
    return chat_id in ADMIN_CHAT_IDS


async def _ensure_user(session, tg_user):
    u = await session.get(User, tg_user.id)
    if u is None:
        u = User(
            chat_id=tg_user.id,
            username=tg_user.username,
            is_admin=tg_user.id in ADMIN_CHAT_IDS,
        )
        session.add(u)
        await session.commit()
    return u


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("await", None)
    chat_id = update.effective_chat.id
    async with async_session() as s:
        await _ensure_user(s, update.effective_user)
        await log_event(s, "start", chat_id=chat_id)
    if is_admin(chat_id):
        await update.message.reply_text(
            "پنل مدیریت خوش آمدید 👇",
            reply_markup=admin_main_menu(),
        )
    else:
        await update.message.reply_text(
            "سلام! برای دریافت پروکسی رایگان دکمه زیر را بزنید 👇",
            reply_markup=user_main_menu(),
        )


async def _serve_proxy(update, context, chat_id, exclude_id=None, skip_gate=False):
    """Core: check join gate, pick a proxy, send the Connect + action buttons.

    exclude_id: if set, try to hand out a DIFFERENT proxy than this one
    (used by 'get another' / after a broken report). Falls back to whatever
    the strategy picks if no alternative exists.
    skip_gate: when True, bypass the gate check entirely. The recheck handler
    uses this after confirming the BLOCK list is clear, so unverifiable
    required channels (which stay in the SHOW list forever) don't re-trigger
    the gate in an endless loop.
    """
    async with async_session() as s:
        user = await _ensure_user(s, update.effective_user)
        await log_event(s, "request_proxy", chat_id=chat_id)
        if not skip_gate:
            # SHOW list includes compulsory channels the bot can't verify, so
            # they still appear to the user. The BLOCK list (verifiable, not
            # joined) is what actually gates: if it's clear, we let the user
            # through even when unverifiable channels remain on screen.
            to_show = await gate_channels(context.bot, s, chat_id)
            if to_show:
                await log_event(s, "join_gate_shown", chat_id=chat_id)
                for ch in to_show:
                    await bump_channel_stat(
                        s, ch.chat_id, "join_prompts", title=ch.title, commit=False
                    )
                await s.commit()
                await render_join_gate(context.bot, chat_id, to_show)
                return
        proxy = await pick_proxy(s)
        if proxy is not None and exclude_id is not None and proxy.id == exclude_id:
            proxy = await pick_proxy(s, exclude_id=exclude_id)
        if proxy is None:
            await update.effective_message.reply_text(
                "فعلاً پروکسی فعالی موجود نیست. لطفاً بعداً تلاش کنید."
            )
            return
        await mark_served(s, proxy, user)
        await log_event(s, "proxy_served", chat_id=chat_id, ref=proxy.id)

        st = await get_settings(s)
        position = (getattr(st, "promo_position", "after") or "after").lower()

        async def _send_proxy():
            await update.effective_message.reply_text(
                "پروکسی شما آماده است! روی دکمه زیر بزنید تا متصل شوید ⚡️",
                reply_markup=proxy_delivery_kb(proxy.link, proxy.id),
            )

        async def _send_promo():
            if not getattr(st, "promo_enabled", False):
                return
            # Only suggest optional channels the user has NOT joined yet.
            # If there is nothing left to join (no optional channels, or the
            # user is already a member of all of them) we show NOTHING — there
            # is no point asking someone to join channels they already joined.
            unjoined = await unjoined_optional_channels(context.bot, s, chat_id)
            # Rotate: show only N sponsor channels at a time (admin-set).
            opt = await pick_promo_channels(
                s, unjoined, getattr(st, "promo_count", 3)
            )
            if not opt:
                return
            await log_event(s, "promo_shown", chat_id=chat_id, commit=False)
            for ch in opt:
                await bump_channel_stat(
                    s, ch.chat_id, "promo_shows", title=ch.title, commit=False
                )
            await s.commit()
            await render_promo(context.bot, chat_id, opt, st.promo_message)

        # Promo can appear BEFORE or AFTER the proxy (admin toggle).
        if position == "before":
            await _send_promo()
            await _send_proxy()
        else:
            await _send_proxy()
            await _send_promo()


async def on_get_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _serve_proxy(update, context, update.effective_chat.id)


async def on_recheck_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    async with async_session() as s:
        await log_event(s, "recheck_click", chat_id=q.from_user.id)
        # BLOCK list = verifiable-and-not-joined. Unverifiable required
        # channels are NOT here, so a channel the bot can't check won't trap
        # the user: once every channel the bot CAN verify is joined, pass.
        blocking = await missing_channels(context.bot, s, q.from_user.id)
    if blocking:
        # Single answer with an alert, then refresh the buttons so ONLY the
        # channels the user still hasn't joined (and we CAN verify) remain.
        await q.answer(
            "هنوز در همه کانال‌ها عضو نیستید. کانال‌های باقی‌مانده در پایین نشان داده شد.",
            show_alert=True,
        )
        try:
            await q.edit_message_reply_markup(reply_markup=join_channels_kb(blocking))
        except Exception:
            pass
        return
    await q.answer("عضویت تایید شد ✅")
    async with async_session() as s:
        await log_event(s, "join_passed", chat_id=q.from_user.id)
    try:
        await q.edit_message_text("عضویت شما تایید شد ✅")
    except Exception:
        pass
    # skip_gate: the BLOCK list is clear; don't re-show the gate for
    # unverifiable channels that will always stay in the SHOW list.
    await _serve_proxy(update, context, q.from_user.id, skip_gate=True)


async def on_another(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User asked for a different proxy than the one just delivered."""
    q = update.callback_query
    await q.answer()
    try:
        exclude_id = int((q.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        exclude_id = None
    await _serve_proxy(update, context, q.from_user.id, exclude_id=exclude_id)


async def on_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User reports a broken proxy -> flag for notify + alert all admins."""
    q = update.callback_query
    try:
        pid = int((q.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        pid = None
    async with async_session() as s:
        user = await _ensure_user(s, q.from_user)
        user.wants_notify = True
        await log_event(s, "report_broken", chat_id=q.from_user.id, ref=pid, commit=False)
        await s.commit()
        pname = None
        plink = None
        if pid is not None:
            p = await s.get(Proxy, pid)
            if p:
                pname = p.name
                plink = p.link
    await q.answer(
        "گزارش شما ثبت شد ✅ به محض آماده‌شدن پروکسی جدید به شما اطلاع داده می‌شود.",
        show_alert=True,
    )
    # Try to immediately offer a different proxy.
    await _serve_proxy(update, context, q.from_user.id, exclude_id=pid)
    # Notify every admin.
    uname = f"@{q.from_user.username}" if q.from_user.username else str(q.from_user.id)
    text = (
        "⚠️ گزارش پروکسی خراب\n"
        f"پروکسی: «{pname or '?'}» (id={pid})\n"
        f"کاربر: {uname} (id={q.from_user.id})"
    )
    for admin_id in ADMIN_CHAT_IDS:
        try:
            await context.bot.send_message(
                admin_id, text, reply_markup=broken_report_kb(pid or 0, plink, reporter_id=q.from_user.id)
            )
        except Exception:
            pass


_MEMBER_OK = {"member", "administrator", "creator", "owner"}


async def _canonical_channel_key(session, chat):
    """Pick the ChannelStat key that matches how the admin stored this channel,
    so verified joins land on the SAME row as join/promo prompts."""
    from sqlalchemy import select
    candidates = []
    if getattr(chat, "username", None):
        candidates.append("@" + chat.username)
    candidates.append(str(chat.id))
    for cand in candidates:
        row = (await session.execute(
            select(Channel.chat_id).where(Channel.chat_id == cand)
        )).scalar_one_or_none()
        if row:
            return cand
    return candidates[0]


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track verified joins/leaves in channels where the bot is an admin.

    Telegram only delivers these `chat_member` updates for chats the bot
    administers, which is exactly the hard limit on membership visibility.
    Counts are stored in channel_stats (keyed by chat_id string) so they
    survive the channel being removed from the config.
    """
    cmu = update.chat_member
    if cmu is None:
        return
    chat = cmu.chat
    if getattr(chat, "type", None) not in ("channel", "supergroup", "group"):
        return
    try:
        old = cmu.old_chat_member.status
        new = cmu.new_chat_member.status
    except AttributeError:
        return
    was = old in _MEMBER_OK
    now = new in _MEMBER_OK
    if was == now:
        return
    async with async_session() as s:
        key = await _canonical_channel_key(s, chat)
        if now and not was:
            await bump_channel_stat(s, key, "joins", title=chat.title)
        elif was and not now:
            await bump_channel_stat(s, key, "leaves", title=chat.title)
