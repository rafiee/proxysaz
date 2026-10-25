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


# ─── Admin side ───


def admin_main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ افزودن پروکسی"), KeyboardButton("📋 لیست پروکسی‌ها")],
            [KeyboardButton("⚙️ روش انتخاب"), KeyboardButton("🔁 چرخش (Rotation)")],
            [KeyboardButton("📢 کانال‌های اجباری"), KeyboardButton("📊 آمار")],
            [KeyboardButton("🚀 دریافت پروکسی")],
        ],
        resize_keyboard=True,
    )


def admin_proxy_row(p):
    status = "🟢" if p.is_active else "⚪️"
    toggle = "غیرفعال" if p.is_active else "فعال"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{toggle}", callback_data=f"px_toggle:{p.id}"),
            InlineKeyboardButton("📌 پین", callback_data=f"px_pin:{p.id}"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"px_del:{p.id}"),
        ]
    ])


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


def channels_kb(channels):
    rows = []
    for ch in channels:
        flag = "🟢 اجباری" if ch.is_required else "⚪️ اختیاری"
        rows.append([
            InlineKeyboardButton(f"{ch.title or ch.chat_id} — {flag}", callback_data=f"ch_toggle:{ch.id}"),
            InlineKeyboardButton("🗑", callback_data=f"ch_del:{ch.id}"),
        ])
    rows.append([InlineKeyboardButton("➕ افزودن کانال", callback_data="ch_add")])
    return InlineKeyboardMarkup(rows)
