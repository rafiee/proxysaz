"""User-facing handlers: /start, 'Get proxy' flow, forced-join gate."""
from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, User
from .keyboards import (
    user_main_menu, admin_main_menu, connect_button, join_channels_kb,
)
from .membership import missing_channels
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


async def _serve_proxy(update, context, chat_id):
    """Core: check join gate, pick a proxy, send the Connect button."""
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
        if proxy is None:
            await update.effective_message.reply_text(
                "فعلاً پروکسی فعالی موجود نیست. لطفاً بعداً تلاش کنید."
            )
            return
        await mark_served(s, proxy, user)
        await update.effective_message.reply_text(
            "پروکسی شما آماده است! روی دکمه زیر بزنید تا متصل شوید ⚡️",
            reply_markup=connect_button(proxy.link),
        )


async def on_get_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _serve_proxy(update, context, update.effective_chat.id)


async def on_recheck_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    async with async_session() as s:
        missing = await missing_channels(context.bot, s, q.from_user.id)
    if missing:
        await q.answer("هنوز در همه کانال‌ها عضو نیستید.", show_alert=True)
        return
    await q.message.reply_text("عضویت تایید شد ✅ دوباره دکمه دریافت پروکسی را بزنید.")
    await _serve_proxy(update, context, q.from_user.id)
