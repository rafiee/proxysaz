"""Inline/reply keyboards. All USER-facing text is Persian."""
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)

# ─── User side ───


def user_main_menu():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("🚀 دریافت پروکسی")]],
        resize_keyboard=True,
    )


def connect_button(link: str):
    """Single big 'Connect' URL button pointing at the t.me proxy link."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⚡️ اتصال به پروکسی", url=link)]]
    )


def proxy_delivery_kb(link: str, proxy_id: int):
    """Connect button + 'report broken' + 'get another' for a delivered proxy."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡️ اتصال به پروکسی", url=link)],
        [InlineKeyboardButton("⚠️ این پروکسی کار نمی‌کند", callback_data=f"report:{proxy_id}")],
        [InlineKeyboardButton("🔄 دریافت پروکسی دیگر", callback_data=f"another:{proxy_id}")],
    ])


def join_channels_kb(channels, invite_fallback=None):
    """Buttons to join each required channel + a recheck button."""
    rows = []
    for ch in channels:
        url = ch.invite_link
        if not url:
            cid = ch.chat_id
            if cid.startswith("@"):
                url = f"https://t.me/{cid[1:]}"
            elif invite_fallback:
                url = invite_fallback
        if url:
            rows.append([InlineKeyboardButton(f"➕ {ch.title or ch.chat_id}", url=url)])
    rows.append([InlineKeyboardButton("✅ عضو شدم، بررسی کن", callback_data="recheck_join")])
    return InlineKeyboardMarkup(rows)


def promo_channels_kb(channels, invite_fallback=None):
    """URL-only buttons for OPTIONAL sponsor channels (no recheck gate)."""
    rows = []
    for ch in channels:
        url = ch.invite_link
        if not url:
            cid = ch.chat_id
            if cid.startswith("@"):
                url = f"https://t.me/{cid[1:]}"
            elif invite_fallback:
                url = invite_fallback
        if url:
            rows.append([InlineKeyboardButton(f"➕ {ch.title or ch.chat_id}", url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ─── Admin side ───


def admin_main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ افزودن پروکسی"), KeyboardButton("📋 لیست پروکسی‌ها")],
            [KeyboardButton("⚙️ روش انتخاب"), KeyboardButton("🔁 چرخش (Rotation)")],
            [KeyboardButton("📢 کانال‌های اجباری"), KeyboardButton("📝 پیام تبلیغاتی")],
            [KeyboardButton("📣 پیام همگانی"), KeyboardButton("📊 آمار")],
            [KeyboardButton("🛠 پیام‌های گزارش"), KeyboardButton("🔄 بروزرسانی منو")],
            [KeyboardButton("🚀 دریافت پروکسی")],
        ],
        resize_keyboard=True,
    )


def admin_proxy_row(p, is_pinned=False):
    # The toggle button shows the CURRENT state (green = active, red = inactive),
    # NOT the next action. Tapping it flips the state and the button re-renders.
    toggle = "🟢 فعال" if p.is_active else "🔴 غیرفعال"
    pin_label = "📌 پین‌شده ✅" if is_pinned else "📌 پین"
    rows = []
    # Tap to open this proxy in Telegram (connect / check), just like a user.
    if getattr(p, "link", None):
        rows.append([InlineKeyboardButton("⚡️ تست/اتصال به پروکسی", url=p.link)])
    rows.append([
        InlineKeyboardButton(f"{toggle}", callback_data=f"px_toggle:{p.id}"),
        InlineKeyboardButton(pin_label, callback_data=f"px_pin:{p.id}"),
        InlineKeyboardButton("🗑 حذف", callback_data=f"px_del:{p.id}"),
    ])
    return InlineKeyboardMarkup(rows)


def selection_strategy_kb(current):
    def mark(v):
        return "✅ " if current == v else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{mark('single')}تک‌پروکسی (ثابت)", callback_data="strat:single")],
        [InlineKeyboardButton(f"{mark('newest')}جدیدترین", callback_data="strat:newest")],
        [InlineKeyboardButton(f"{mark('spread')}توزیع مساوی (کمترین استفاده)", callback_data="strat:spread")],
    ])


def rotation_kb(mode, hours):
    def mark(v):
        return "✅ " if mode == v else ""
    rows = [
        [InlineKeyboardButton(f"{mark('manual')}دستی", callback_data="rot:manual")],
        [InlineKeyboardButton(f"{mark('auto')}خودکار (هر {hours} ساعت)", callback_data="rot:auto")],
        [InlineKeyboardButton("⏱ تنظیم بازه (ساعت)", callback_data="rot:sethours")],
        [InlineKeyboardButton("🔄 چرخش دستی همین الان", callback_data="rot:now")],
    ]
    return InlineKeyboardMarkup(rows)


def channels_kb(channels, force_enabled=True):
    rows = []
    fj = "🔔 اجبار عضویت: روشن" if force_enabled else "🔕 اجبار عضویت: خاموش"
    rows.append([InlineKeyboardButton(fj, callback_data="fj_toggle")])
    for ch in channels:
        flag = "🟢 اجباری" if ch.is_required else "⚪️ اختیاری"
        rows.append([
            InlineKeyboardButton(f"{ch.title or ch.chat_id} — {flag}", callback_data=f"ch_toggle:{ch.id}"),
            InlineKeyboardButton("🗑", callback_data=f"ch_del:{ch.id}"),
        ])
    rows.append([InlineKeyboardButton("➕ افزودن کانال", callback_data="ch_add")])
    return InlineKeyboardMarkup(rows)


def notify_prompt_kb(proxy_id: int):
    """Ask the admin whether to notify users about a newly added proxy."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 اطلاع به گزارش‌دهندگان", callback_data=f"notify:reporters:{proxy_id}")],
        [InlineKeyboardButton("📢 اطلاع به همه کاربران", callback_data=f"notify:all:{proxy_id}")],
        [InlineKeyboardButton("خیر، لازم نیست", callback_data="notify:no:0")],
    ])


def broken_report_kb(proxy_id: int, link: str = None, reporter_id: int = 0):
    """Buttons attached to the admin notice when a user reports a broken proxy.

    If `link` is given, a URL 'Test' button is added that opens the proxy in
    the admin's own Telegram — exactly like a normal user connecting — so the
    admin tests it with their real client/network instead of a server-side probe.

    If `reporter_id` is given, two reply buttons let the admin answer the
    reporting user directly: confirm the proxy is healthy, or tell them it is
    being fixed (which also re-subscribes them to the 'new proxy' notification).
    """
    rows = []
    if link:
        rows.append([InlineKeyboardButton("🧪 تست پروکسی (اتصال)", url=link)])
    if reporter_id:
        rows.append([
            InlineKeyboardButton("✅ سالم است (اطلاع به کاربر)",
                                 callback_data=f"rpt_ok:{proxy_id}:{reporter_id}"),
            InlineKeyboardButton("🛠 در حال رفع (اطلاع به کاربر)",
                                 callback_data=f"rpt_fix:{proxy_id}:{reporter_id}"),
        ])
        rows.append([
            InlineKeyboardButton("✏️ پیام دلخواه به کاربر",
                                 callback_data=f"rpt_msg:{proxy_id}:{reporter_id}"),
        ])
    rows.append([InlineKeyboardButton("⚪️ غیرفعال کردن این پروکسی", callback_data=f"rpt_off:{proxy_id}")])
    return InlineKeyboardMarkup(rows)


def broadcast_admin_kb(auto_enabled: bool, hours: int):
    """Admin controls for the broadcast feature (manual + automatic)."""
    auto = "🟢 خودکار: روشن" if auto_enabled else "⚪️ خودکار: خاموش"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ارسال دستی (الان)", callback_data="bc_manual")],
        [InlineKeyboardButton("✏️ ویرایش آخرین پیام همگانی", callback_data="bc_edit_last")],
        [InlineKeyboardButton(auto, callback_data="bc_auto_toggle")],
        [InlineKeyboardButton("✏️ تنظیم متن خودکار (HTML)", callback_data="bc_auto_set")],
        [InlineKeyboardButton(f"⏱ بازه ارسال: هر {hours} ساعت", callback_data="bc_auto_hours")],
        [InlineKeyboardButton("👁 پیش‌نمایش متن خودکار", callback_data="bc_auto_preview")],
    ])


def broadcast_interval_kb():
    """Quick presets for the automatic-broadcast interval."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("هر ۱۲ ساعت (نیم روز)", callback_data="bc_int:12")],
        [InlineKeyboardButton("هر روز (۲۴ ساعت)", callback_data="bc_int:24")],
        [InlineKeyboardButton("یک روز در میان (۴۸ ساعت)", callback_data="bc_int:48")],
        [InlineKeyboardButton("تعداد ساعت دلخواه", callback_data="bc_int:custom")],
    ])


def promo_admin_kb(enabled: bool):
    """Admin controls for the promotional message."""
    toggle = "🟢 تبلیغ: روشن" if enabled else "⚪️ تبلیغ: خاموش"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle, callback_data="promo_toggle")],
        [InlineKeyboardButton("✏️ تنظیم متن پیام (HTML)", callback_data="promo_set")],
        [InlineKeyboardButton("🔢 تعداد کانال نمایشی (N)", callback_data="promo_count")],
        [InlineKeyboardButton("👁 پیش‌نمایش پیام", callback_data="promo_preview")],
    ])


def report_messages_kb():
    """Admin controls to edit the two canned replies sent to a user who
    reported a broken proxy (the '✅ healthy' and '🛠 being fixed' messages)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ویرایش پیام «سالم است»", callback_data="rpm_set_ok")],
        [InlineKeyboardButton("✏️ ویرایش پیام «در حال رفع»", callback_data="rpm_set_fix")],
        [InlineKeyboardButton("👁 پیش‌نمایش هر دو پیام", callback_data="rpm_preview")],
        [InlineKeyboardButton("♻️ بازگرداندن به پیش‌فرض", callback_data="rpm_reset")],
    ])
