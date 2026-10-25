"""User-facing handlers: /start, 'Get proxy' flow, forced-join gate."""
from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, User, Proxy, get_settings
from .keyboards import (
    user_main_menu, admin_main_menu, connect_button, join_channels_kb,
    proxy_delivery_kb, broken_report_kb, promo_channels_kb,
)
from .membership import missing_channels, optional_channels
from .rotation import pick_proxy, mark_served

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


async def _serve_proxy(update, context, chat_id, exclude_id=None):
    """Core: check join gate, pick a proxy, send the Connect + action buttons.

    exclude_id: if set, try to hand out a DIFFERENT proxy than this one
    (used by 'get another' / after a broken report). Falls back to whatever
    the strategy picks if no alternative exists.
    """
    async with async_session() as s:
        user = await _ensure_user(s, update.effective_user)
        missing = await missing_channels(context.bot, s, chat_id)
        if missing:
            await update.effective_message.reply_text(
                "برای دریافت پروکسی، ابتدا در کانال‌های زیر عضو شوید:",
                reply_markup=join_channels_kb(missing),
            )
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
        await update.effective_message.reply_text(
            "پروکسی شما آماده است! روی دکمه زیر بزنید تا متصل شوید ⚡️",
            reply_markup=proxy_delivery_kb(proxy.link, proxy.id),
        )
        # Optional sponsor promo shown AFTER the proxy.
        st = await get_settings(s)
        if getattr(st, "promo_enabled", False):
            opt = await optional_channels(s)
            promo_text = (st.promo_message or "").strip()
            if promo_text or opt:
                body = promo_text or "برای حمایت از اسپانسرها، می‌توانید در کانال‌های زیر عضو شوید 🙏"
                try:
                    await update.effective_message.reply_text(
                        body,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=promo_channels_kb(opt),
                    )
                except Exception:
                    # Fall back to plain text if the admin's HTML is malformed.
                    await update.effective_message.reply_text(
                        body, reply_markup=promo_channels_kb(opt)
                    )


async def on_get_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _serve_proxy(update, context, update.effective_chat.id)


async def on_recheck_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    async with async_session() as s:
        missing = await missing_channels(context.bot, s, q.from_user.id)
    if missing:
        # Single answer with an alert, then refresh the buttons so ONLY the
        # channels the user still hasn't joined remain.
        await q.answer(
            "هنوز در همه کانال‌ها عضو نیستید. کانال‌های باقی‌مانده در پایین نشان داده شد.",
            show_alert=True,
        )
        try:
            await q.edit_message_reply_markup(reply_markup=join_channels_kb(missing))
        except Exception:
            pass
        return
    await q.answer("عضویت تایید شد ✅")
    try:
        await q.edit_message_text("عضویت شما تایید شد ✅")
    except Exception:
        pass
    await _serve_proxy(update, context, q.from_user.id)


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
        await s.commit()
        pname = None
        if pid is not None:
            p = await s.get(Proxy, pid)
            pname = p.name if p else None
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
                admin_id, text, reply_markup=broken_report_kb(pid or 0)
            )
        except Exception:
            pass
