"""Admin menu buttons + the single text-dispatch handler (await-state driven)."""
from sqlalchemy import select, func

from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, get_settings, Proxy, Channel, User
from .keyboards import (
    selection_strategy_kb, rotation_kb, channels_kb, admin_proxy_row,
    notify_prompt_kb, promo_admin_kb,
)
from .proxy_utils import parse_proxy_link, ProxyParseError

# Menu button labels
BTN_ADD = "➕ افزودن پروکسی"
BTN_LIST = "📋 لیست پروکسی‌ها"
BTN_STRAT = "⚙️ روش انتخاب"
BTN_ROT = "🔁 چرخش (Rotation)"
BTN_CH = "📢 کانال‌های اجباری"
BTN_PROMO = "📝 پیام تبلیغاتی"
BTN_STATS = "📊 آمار"


def is_admin(chat_id: int) -> bool:
    return chat_id in ADMIN_CHAT_IDS


async def admin_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle an admin MENU button press. Return True if it was handled."""
    text = (update.message.text or "").strip()
    if text == BTN_ADD:
        context.user_data["await"] = "proxy_link"
        await update.message.reply_text(
            "لینک پروکسی را بفرستید (تک لینک):\n"
            "مثال: https://t.me/proxy?server=1.2.3.4&port=443&secret=ee..."
        )
        return True
    if text == BTN_LIST:
        await _list_proxies(update)
        return True
    if text == BTN_STRAT:
        async with async_session() as s:
            st = await get_settings(s)
            await update.message.reply_text(
                "روش انتخاب پروکسی را انتخاب کنید:",
                reply_markup=selection_strategy_kb(st.selection_strategy),
            )
        return True
    if text == BTN_ROT:
        async with async_session() as s:
            st = await get_settings(s)
            await update.message.reply_text(
                "تنظیمات چرخش پروکسی:",
                reply_markup=rotation_kb(st.rotation_mode, st.rotation_hours or 0),
            )
        return True
    if text == BTN_CH:
        await _list_channels(update)
        return True
    if text == BTN_PROMO:
        await _promo_panel(update)
        return True
    if text == BTN_STATS:
        await _stats(update)
        return True
    return False


async def admin_await_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle a pending admin input step. Return True if it was consumed."""
    action = context.user_data.get("await")
    if not action:
        return False
    text = (update.message.text or "").strip()

    if action == "proxy_link":
        try:
            parsed = parse_proxy_link(text)
        except ProxyParseError as e:
            await update.message.reply_text(f"لینک نامعتبر است: {e}\nدوباره بفرستید.")
            return True
        context.user_data["pending_proxy"] = parsed
        context.user_data["await"] = "proxy_name"
        await update.message.reply_text(
            "لینک دریافت شد ✅\nحالا یک نام داخلی برای این پروکسی بفرستید "
            "(فقط شما می‌بینید):"
        )
        return True

    if action == "proxy_name":
        parsed = context.user_data.pop("pending_proxy", None)
        context.user_data.pop("await", None)
        if not parsed:
            await update.message.reply_text("خطا در فرآیند. دوباره از ابتدا شروع کنید.")
            return True
        async with async_session() as s:
            p = Proxy(
                name=text or "proxy",
                link=parsed["link"],
                proxy_type=parsed["type"],
                server=parsed["server"],
                port=parsed["port"],
                secret=parsed.get("secret"),
                is_active=True,
            )
            s.add(p)
            await s.commit()
            new_id = p.id
        await update.message.reply_text(
            f"پروکسی «{text}» ذخیره و فعال شد ✅\nآیا به کاربران اطلاع داده شود؟",
            reply_markup=notify_prompt_kb(new_id),
        )
        return True

    if action == "rot_hours":
        context.user_data.pop("await", None)
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("عدد ساعت را به صورت صحیح بفرستید (مثلاً 6).")
            return True
        async with async_session() as s:
            st = await get_settings(s)
            st.rotation_hours = int(text)
            await s.commit()
        await update.message.reply_text(f"بازه چرخش روی {text} ساعت تنظیم شد ✅")
        return True

    if action == "channel_add":
        context.user_data.pop("await", None)
        parts = text.split("|")
        chat_id = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else None
        # If the admin didn't give a title, try to fetch the real channel title
        # (which can include emojis) via the bot.
        if not title:
            try:
                chat = await update.get_bot().get_chat(chat_id)
                title = chat.title or chat_id
            except Exception:
                title = chat_id
        async with async_session() as s:
            s.add(Channel(chat_id=chat_id, title=title, is_required=True))
            await s.commit()
        await update.message.reply_text(f"کانال «{title}» اضافه شد ✅")
        return True

    if action == "promo_message":
        context.user_data.pop("await", None)
        async with async_session() as s:
            st = await get_settings(s)
            st.promo_message = update.message.text_html or text
            await s.commit()
        await update.message.reply_text(
            "متن تبلیغاتی ذخیره شد ✅\nبرای فعال شدن نمایش، از دکمه تبلیغ: روشن استفاده کنید.",
        )
        await _promo_panel(update)
        return True

    return False


async def _list_proxies(update: Update):
    async with async_session() as s:
        res = await s.execute(select(Proxy).order_by(Proxy.id))
        proxies = list(res.scalars().all())
        st = await get_settings(s)
    if not proxies:
        await update.message.reply_text("هیچ پروکسی‌ای ثبت نشده است.")
        return
    for p in proxies:
        pin = " 📌" if st.pinned_proxy_id == p.id else ""
        txt = (
            f"«{p.name}»{pin}\n"
            f"نوع: {p.proxy_type} | سرور: {p.server}:{p.port}\n"
            f"دفعات ارائه: {p.served_count}"
        )
        await update.message.reply_text(txt, reply_markup=admin_proxy_row(p))


async def _list_channels(update: Update):
    async with async_session() as s:
        res = await s.execute(select(Channel).order_by(Channel.id))
        channels = list(res.scalars().all())
        st = await get_settings(s)
    await update.message.reply_text(
        "کانال‌های اجباری (روی هرکدام بزنید تا اجباری/اختیاری شود):\n"
        "برای افزودن، شناسه کانال به صورت `@username | عنوان` بفرستید.",
        reply_markup=channels_kb(channels, force_enabled=getattr(st, "force_join_enabled", True)),
        parse_mode="Markdown",
    )


async def _promo_panel(update: Update):
    async with async_session() as s:
        st = await get_settings(s)
        enabled = getattr(st, "promo_enabled", False)
        has_msg = bool((st.promo_message or "").strip())
    status = "روشن 🟢" if enabled else "خاموش ⚪️"
    msg_state = "تنظیم شده" if has_msg else "خالی"
    await update.message.reply_text(
        "📝 پیام تبلیغاتی (پس از تحویل پروکسی نمایش داده می‌شود)\n"
        f"وضعیت: {status} | متن: {msg_state}\n\n"
        "کانال‌های اختیاری (اسپانسر) همان کانال‌هایی هستند که در بخش کانال‌ها "
        "روی حالت «اختیاری» تنظیم شده‌اند و زیر پیام تبلیغاتی به کاربر پیشنهاد می‌شوند.",
        reply_markup=promo_admin_kb(enabled),
    )


async def _stats(update: Update):
    async with async_session() as s:
        n_proxies = (await s.execute(select(func.count()).select_from(Proxy))).scalar() or 0
        n_active = (await s.execute(
            select(func.count()).select_from(Proxy).where(Proxy.is_active == True)  # noqa: E712
        )).scalar() or 0
        n_users = (await s.execute(select(func.count()).select_from(User))).scalar() or 0
        total_served = (await s.execute(select(func.coalesce(func.sum(Proxy.served_count), 0)))).scalar() or 0
        n_channels = (await s.execute(select(func.count()).select_from(Channel))).scalar() or 0
    await update.message.reply_text(
        "📊 آمار ربات\n"
        f"پروکسی‌ها: {n_proxies} (فعال: {n_active})\n"
        f"کاربران: {n_users}\n"
        f"کل دفعات ارائه پروکسی: {total_served}\n"
        f"کانال‌ها: {n_channels}"
    )
