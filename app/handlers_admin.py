"""Admin menu buttons + the single text-dispatch handler (await-state driven)."""
from sqlalchemy import select, func

from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, get_settings, Proxy, Channel, User, ProxyUser
from .keyboards import (
    selection_strategy_kb, rotation_kb, channels_kb, admin_proxy_row,
    notify_prompt_kb, promo_admin_kb, broadcast_admin_kb, report_messages_kb,
)
from .proxy_utils import parse_proxy_link, ProxyParseError
from .stats import gather_stats, render_stats
from .broadcast import do_broadcast, edit_last_broadcast, push_menu_to_all
from .texts import DEFAULT_REPORT_OK, DEFAULT_REPORT_FIX

# Menu button labels
BTN_ADD = "➕ افزودن پروکسی"
BTN_LIST = "📋 لیست پروکسی‌ها"
BTN_STRAT = "⚙️ روش انتخاب"
BTN_ROT = "🔁 چرخش (Rotation)"
BTN_CH = "📢 کانال‌های اجباری"
BTN_PROMO = "📝 پیام تبلیغاتی"
BTN_BROADCAST = "📣 پیام همگانی"
BTN_STATS = "📊 آمار"
BTN_REPORTS = "🛠 پیام‌های گزارش"
BTN_REFRESH = "🔄 بروزرسانی منو"


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
    if text == BTN_BROADCAST:
        await _broadcast_panel(update)
        return True
    if text == BTN_STATS:
        await _stats(update)
        return True
    if text == BTN_REPORTS:
        await _report_messages_panel(update)
        return True
    if text == BTN_REFRESH:
        await update.message.reply_text("در حال بروزرسانی منو برای همه کاربران… ⏳")
        sent, failed = await push_menu_to_all(update.get_bot())
        await update.message.reply_text(
            f"✅ منوی به‌روز برای کاربران ارسال شد.\nموفق: {sent} | ناموفق: {failed}"
        )
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

    if action == "promo_count":
        context.user_data.pop("await", None)
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("یک عدد صحیح بزرگ‌تر از صفر بفرستید (مثلاً 3).")
            return True
        async with async_session() as s:
            st = await get_settings(s)
            st.promo_count = int(text)
            await s.commit()
        await update.message.reply_text(f"در هر بار حداکثر {text} کانال اختیاری نمایش داده می‌شود ✅")
        await _promo_panel(update)
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

    if action == "broadcast_manual":
        context.user_data.pop("await", None)
        html_text = update.message.text_html or text
        if not html_text.strip():
            await update.message.reply_text("متن خالی است. دوباره تلاش کنید.")
            return True
        await update.message.reply_text("ارسال پیام همگانی آغاز شد… ⁨⏳⁩")
        sent, failed = await do_broadcast(update.get_bot(), html_text, mode="manual", record=True)
        await update.message.reply_text(
            f"✅ پیام همگانی ارسال شد.\nموفق: {sent} | ناموفق (بلاک/خطا): {failed}\n\n"
            "اگر اشتباهی دارد، از دکمه«✅️ ویرایش آخرین پیام همگانی» در پنل پیام همگانی استفاده کنید."
        )
        return True

    if action == "broadcast_auto_message":
        context.user_data.pop("await", None)
        async with async_session() as s:
            st = await get_settings(s)
            st.broadcast_auto_message = update.message.text_html or text
            await s.commit()
        await update.message.reply_text(
            "متن پیام همگانی خودکار ذخیره شد ✅\nبرای ارسال دوره‌ای، گزینه خودکار را روشن کنید."
        )
        await _broadcast_panel(update)
        return True

    if action == "broadcast_hours":
        context.user_data.pop("await", None)
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("عدد ساعت را به صورت صحیح بفرستید (مثلاً 24).")
            return True
        async with async_session() as s:
            st = await get_settings(s)
            st.broadcast_auto_hours = int(text)
            await s.commit()
        await update.message.reply_text(f"بازه ارسال خودکار روی هر {text} ساعت تنظیم شد ✅")
        await _broadcast_panel(update)
        return True

    if action == "broadcast_edit":
        context.user_data.pop("await", None)
        html_text = update.message.text_html or text
        if not html_text.strip():
            await update.message.reply_text("متن خالی است. دوباره تلاش کنید.")
            return True
        await update.message.reply_text("در حال ویرایش آخرین پیام همگانی… ⏳")
        edited, failed, found = await edit_last_broadcast(update.get_bot(), html_text)
        if not found:
            await update.message.reply_text(
                "پیام همگانی قابل ویرایشی یافت نشد. (فقط آخرین پیام دستی قابل ویرایش است.)"
            )
            return True
        await update.message.reply_text(
            f"✅ آخرین پیام همگانی ویرایش شد.\nویرایش‌شده: {edited} | ناموفق: {failed}\n\n"
            "نکته: تلگرام اجازه ویرایش پیام را تا ۴۸ ساعت می‌دهد؛ پیام‌های قدیمی‌تر ویرایش نمی‌شوند."
        )
        return True

    if action == "report_msg_ok":
        context.user_data.pop("await", None)
        async with async_session() as s:
            st = await get_settings(s)
            st.report_ok_message = update.message.text_html or text
            await s.commit()
        await update.message.reply_text("پیام «سالم است» ذخیره شد ✅")
        await _report_messages_panel(update)
        return True

    if action == "report_msg_fix":
        context.user_data.pop("await", None)
        async with async_session() as s:
            st = await get_settings(s)
            st.report_fix_message = update.message.text_html or text
            await s.commit()
        await update.message.reply_text("پیام «در حال رفع» ذخیره شد ✅")
        await _report_messages_panel(update)
        return True

    if action == "report_custom":
        context.user_data.pop("await", None)
        target = context.user_data.pop("report_target", None)
        html_text = update.message.text_html or text
        if not target:
            await update.message.reply_text("کاربر مقصد مشخص نیست. دوباره از دکمه استفاده کنید.")
            return True
        if not html_text.strip():
            await update.message.reply_text("متن خالی است. دوباره تلاش کنید.")
            return True
        try:
            try:
                await update.get_bot().send_message(
                    int(target), html_text, parse_mode="HTML", disable_web_page_preview=True
                )
            except Exception:
                await update.get_bot().send_message(int(target), html_text, disable_web_page_preview=True)
            await update.message.reply_text("✅ پیام دلخواه به کاربر ارسال شد.")
        except Exception:
            await update.message.reply_text("❌ ارسال ناموفق بود (شاید کاربر ربات را بلاک کرده است).")
        return True

    if action == "channel_text":
        context.user_data.pop("await", None)
        cid = context.user_data.pop("channel_cfg_id", None)
        html_text = update.message.text_html or text
        if not cid:
            await update.message.reply_text("کانال مشخص نیست. دوباره از دکمه استفاده کنید.")
            return True
        if not html_text.strip():
            await update.message.reply_text("متن خالی است. دوباره تلاش کنید.")
            return True
        async with async_session() as s:
            ch = await s.get(Channel, int(cid))
            if ch is None:
                await update.message.reply_text("کانال یافت نشد.")
                return True
            ch.desc_html = html_text
            if not getattr(ch, "desc_enabled", False):
                ch.desc_enabled = True
            await s.commit()
        await update.message.reply_text("✅ متن توضیحات کانال ذخیره شد (توضیحات روشن شد 🟢).")
        return True


async def admin_photo_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle a pending admin photo-upload step. Return True if consumed."""
    action = context.user_data.get("await")
    if action != "channel_img":
        return False
    if not update.message or not update.message.photo:
        await update.message.reply_text("عکسی دریافت نشد. لطفاً یک عکس بفرستید.")
        return True
    context.user_data.pop("await", None)
    cid = context.user_data.pop("channel_cfg_id", None)
    if not cid:
        await update.message.reply_text("کانال مشخص نیست. دوباره از دکمه استفاده کنید.")
        return True
    file_id = update.message.photo[-1].file_id
    async with async_session() as s:
        ch = await s.get(Channel, int(cid))
        if ch is None:
            await update.message.reply_text("کانال یافت نشد.")
            return True
        ch.desc_image = file_id
        if not getattr(ch, "desc_enabled", False):
            ch.desc_enabled = True
        await s.commit()
    await update.message.reply_text("✅ تصویر کانال ذخیره شد (توضیحات روشن شد 🟢).")
    return True


async def build_proxy_card(session, p, st):
    """Build the (text, keyboard) card for one proxy, reflecting its CURRENT
    enabled/disabled + pinned state. Shared by the list view and the inline
    callbacks so a toggle/pin instantly re-renders to the right state."""
    uniq_users = (await session.execute(
        select(func.count(func.distinct(ProxyUser.chat_id)))
        .where(ProxyUser.proxy_id == p.id)
    )).scalar() or 0
    is_pinned = (st.pinned_proxy_id == p.id)
    pin = " 📌" if is_pinned else ""
    state = "🟢 فعال" if p.is_active else "🔴 غیرفعال"
    txt = (
        f"«{p.name}»{pin}\n"
        f"وضعیت: {state}{'  |  📌 پین‌شده' if is_pinned else ''}\n"
        f"نوع: {p.proxy_type} | سرور: {p.server}:{p.port}\n"
        f"دفعات ارائه: {p.served_count} | کاربران یکتا: {uniq_users}"
    )
    return txt, admin_proxy_row(p, is_pinned=is_pinned)


async def _list_proxies(update: Update):
    async with async_session() as s:
        res = await s.execute(select(Proxy).order_by(Proxy.id))
        proxies = list(res.scalars().all())
        st = await get_settings(s)
        if not proxies:
            await update.message.reply_text("هیچ پروکسی‌ای ثبت نشده است.")
            return
        for p in proxies:
            txt, markup = await build_proxy_card(s, p, st)
            await update.message.reply_text(txt, reply_markup=markup)


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
        count = getattr(st, "promo_count", 3)
        position = getattr(st, "promo_position", "after")
    status = "روشن 🟢" if enabled else "خاموش ⚪️"
    msg_state = "تنظیم شده" if has_msg else "خالی"
    pos_state = "قبل از پروکسی" if position == "before" else "بعد از پروکسی"
    await update.message.reply_text(
        "📝 پیام تبلیغاتی (قبل یا بعد از تحویل پروکسی نمایش داده می‌شود)\n"
        f"وضعیت: {status} | متن: {msg_state} | تعداد نمایشی: {count} | جایگاه: {pos_state}\n\n"
        "کانال‌های اختیاری (اسپانسر) همان کانال‌هایی هستند که در بخش کانال‌ها "
        "روی حالت «اختیاری» تنظیم شده‌اند و زیر پیام تبلیغاتی به کاربر پیشنهاد می‌شوند.\n"
        "فقط کانال‌هایی که کاربر هنوز عضو نشده نمایش داده می‌شوند، آن هم حداکثر به تعداد نمایشی و به صورت چرخشی.",
        reply_markup=promo_admin_kb(enabled, position),
    )


async def _broadcast_panel(update: Update):
    async with async_session() as s:
        st = await get_settings(s)
        auto = getattr(st, "broadcast_auto_enabled", False)
        hours = int(getattr(st, "broadcast_auto_hours", 24) or 24)
        has_msg = bool((st.broadcast_auto_message or "").strip())
        last = st.broadcast_last_sent_at
    auto_state = "روشن 🟢" if auto else "خاموش ⚪️"
    msg_state = "تنظیم شده" if has_msg else "خالی"
    last_txt = last.strftime("%Y-%m-%d %H:%M UTC") if last else "—"
    await update.message.reply_text(
        "📣 پیام همگانی (Broadcast)\n\n"
        "• ارسال دستی: یک متن (با پشتیبانی HTML) را همین الان به همه کاربران بفرستید.\n"
        "• ارسال خودکار: یک متن ثابت تنظیم کنید تا به صورت دوره‌ای ارسال شود.\n\n"
        f"وضعیت خودکار: {auto_state} | متن خودکار: {msg_state} | بازه: هر {hours} ساعت\n"
        f"آخرین ارسال خودکار: {last_txt}",
        reply_markup=broadcast_admin_kb(auto, hours),
    )


async def _stats(update: Update):
    async with async_session() as s:
        data = await gather_stats(s)
    text = render_stats(data)
    # Telegram caps a message at 4096 chars; split long reports safely.
    if len(text) <= 4000:
        await update.message.reply_text(text, parse_mode="HTML", disable_web_page_preview=True)
        return
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 4000:
            await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await update.message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)


async def _report_messages_panel(update: Update):
    """Panel to edit the two canned replies sent to a user who reported a
    broken proxy (the '✅ healthy' and '🛠 being fixed' messages)."""
    async with async_session() as s:
        st = await get_settings(s)
        has_ok = bool((getattr(st, "report_ok_message", None) or "").strip())
        has_fix = bool((getattr(st, "report_fix_message", None) or "").strip())
    ok_state = "سفارشی ✍️" if has_ok else "پیش‌فرض"
    fix_state = "سفارشی ✍️" if has_fix else "پیش‌فرض"
    await update.message.reply_text(
        "🛠 پیام‌های پاسخ به گزارش خرابی\n\n"
        "این دو پیام زمانی به کاربرِ گزارش‌دهنده ارسال می‌شوند که شما روی دکمه‌های "
        "«✅ سالم است» یا «🛠 در حال رفع» بزنید.\n"
        "می‌توانید متن آن‌ها را سفارشی کنید (HTML پشتیبانی می‌شود).\n\n"
        f"• پیام «سالم است»: {ok_state}\n"
        f"• پیام «در حال رفع»: {fix_state}",
        reply_markup=report_messages_kb(),
    )
