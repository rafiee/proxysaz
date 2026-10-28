"""Entry point: wire up python-telegram-bot application and run polling."""
import logging

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ChatMemberHandler, ContextTypes, filters,
)

from .config import BOT_TOKEN
from .database import init_db
from .handlers_user import (
    cmd_start, on_get_proxy, on_recheck_join, on_report, on_another,
    on_chat_member, is_admin, GET_PROXY_TEXT,
)
from .handlers_admin import admin_menu_router, admin_await_router, admin_photo_router
from .handlers_admin_cb import admin_callback
from .broadcast import auto_broadcast_tick

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("proxy-bot")


async def text_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single entry for all non-command text (avoids ConversationHandler bugs)."""
    msg = update.message
    if msg is None or msg.text is None:
        return
    chat_id = update.effective_chat.id
    text = msg.text.strip()

    # The 'Get proxy' button works for everyone (admins have it too).
    if text == GET_PROXY_TEXT:
        context.user_data.pop("await", None)
        await on_get_proxy(update, context)
        return

    if is_admin(chat_id):
        # 1) pending input step takes priority
        if await admin_await_router(update, context):
            return
        # 2) menu buttons
        if await admin_menu_router(update, context):
            return

    # Fallback for ordinary users.
    if not is_admin(chat_id):
        await on_get_proxy(update, context)


async def photo_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route admin photo uploads (e.g. per-channel description image)."""
    msg = update.message
    if msg is None or not msg.photo:
        return
    chat_id = update.effective_chat.id
    if is_admin(chat_id):
        await admin_photo_router(update, context)


async def _post_init(app: Application):
    await init_db()
    log.info("Database initialized.")
    # Schedule the automatic broadcast tick (self-gates on interval + enabled).
    jq = getattr(app, "job_queue", None)
    if jq is not None:
        jq.run_repeating(auto_broadcast_tick, interval=3600, first=120)
        log.info("Auto-broadcast job scheduled (hourly check).")
    else:
        log.warning(
            "JobQueue unavailable — automatic broadcast disabled. "
            "Install python-telegram-bot[job-queue] to enable it."
        )


def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_recheck_join, pattern=r"^recheck_join$"))
    app.add_handler(CallbackQueryHandler(on_report, pattern=r"^report:"))
    app.add_handler(CallbackQueryHandler(on_another, pattern=r"^another:"))
    app.add_handler(CallbackQueryHandler(
        admin_callback,
        pattern=r"^(strat:|rot:|px_|chd_|ch_|fj_toggle|notify:|rpt_|rpm_|promo_|bc_)",
    ))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_dispatch))
    app.add_handler(MessageHandler(filters.PHOTO, photo_dispatch))
    # Track verified joins/leaves in channels where the bot is an admin.
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    return app


def main():
    app = build_app()
    log.info("Starting proxy bot (polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
