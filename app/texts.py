"""Editable default message templates (Persian).

These are the fallbacks used when the admin has not set a custom version in
BotSettings. Keeping them here means the send-side and the edit-panel agree on
the same defaults.
"""

# Shown to a reporting user when the admin marks the proxy as healthy.
DEFAULT_REPORT_OK = (
    "✅ پروکسی شما بررسی شد و سالم است.\n"
    "لطفاً اتصال اینترنت و اپ تلگرام خود را بررسی کنید و دوباره وصل شوید."
)

# Shown to a reporting user when the admin marks the proxy as being fixed.
DEFAULT_REPORT_FIX = (
    "🛠 گزارش شما بررسی شد. مشکل به‌زودی برطرف می‌شود.\n"
    "به‌محض آماده‌شدن پروکسی جدید، به شما اطلاع می‌دهیم. ممنون از گزارش شما 🙏"
)
