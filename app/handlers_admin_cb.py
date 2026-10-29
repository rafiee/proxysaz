"""Admin inline-callback handlers: strategy, rotation, proxy & channel ops."""
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, get_settings, Proxy, Channel, User
from .keyboards import (
    selection_strategy_kb, rotation_kb, channels_kb, promo_admin_kb, admin_proxy_row,
    broadcast_admin_kb, broadcast_interval_kb, report_messages_kb, channel_config_kb,
)
from .broadcast import do_broadcast
from .texts import DEFAULT_REPORT_OK, DEFAULT_REPORT_FIX


def _is_admin(uid):
    return uid in ADMIN_CHAT_IDS


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_admin(q.from_user.id):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return
    data = q.data or ""

    # ── Settings sub-menu entries ──
    if data.startswith("set:"):
        sub = data.split(":", 1)[1]
        await q.answer()
        async with async_session() as s:
            st = await get_settings(s)
            if sub == "strat":
                await q.message.reply_text(
                    "روش انتخاب پروکسی را انتخاب کنید:",
                    reply_markup=selection_strategy_kb(st.selection_strategy),
                )
            elif sub == "health":
                await q.message.reply_text(
                    "⏱ دوره بررسی سلامت پروکسی (چرخش):\n"
                    "در حالت خودکار، ربات هر چند ساعت یک‌بار پروکسی فعال را چرخش می‌دهد.",
                    reply_markup=rotation_kb(st.rotation_mode, st.rotation_hours or 0),
                )
            elif sub == "reports":
                has_ok = bool((getattr(st, "report_ok_message", None) or "").strip())
                has_fix = bool((getattr(st, "report_fix_message", None) or "").strip())
                ok_state = "سفارشی ✍️" if has_ok else "پیش‌فرض"
                fix_state = "سفارشی ✍️" if has_fix else "پیش‌فرض"
                await q.message.reply_text(
                    "🛠 پیام‌های پاسخ به گزارش خرابی\n\n"
                    "این دو پیام زمانی به کاربرِ گزارش‌دهنده ارسال می‌شوند که شما روی دکمه‌های "
                    "«✅ سالم است» یا «🛠 در حال رفع» بزنید.\n\n"
                    f"• پیام «سالم است»: {ok_state}\n"
                    f"• پیام «در حال رفع»: {fix_state}",
                    reply_markup=report_messages_kb(),
                )
            elif sub == "promo":
                enabled = getattr(st, "promo_enabled", False)
                has_msg = bool((st.promo_message or "").strip())
                count = getattr(st, "promo_count", 3)
                position = getattr(st, "promo_position", "after")
                status = "روشن 🟢" if enabled else "خاموش ⚪️"
                msg_state = "تنظیم شده" if has_msg else "خالی"
                pos_state = "قبل از پروکسی" if position == "before" else "بعد از پروکسی"
                await q.message.reply_text(
                    "📝 پیام تبلیغاتی (قبل یا بعد از تحویل پروکسی نمایش داده می‌شود)\n"
                    f"وضعیت: {status} | متن: {msg_state} | تعداد نمایشی: {count} | جایگاه: {pos_state}\n\n"
                    "کانال‌های اختیاری (اسپانسر) همان کانال‌هایی هستند که در بخش کانال‌ها "
                    "روی حالت «اختیاری» تنظیم شده‌اند و زیر پیام تبلیغاتی به کاربر پیشنهاد می‌شوند.",
                    reply_markup=promo_admin_kb(enabled, position),
                )
            elif sub == "refresh":
                from .keyboards import admin_main_menu
                await q.message.reply_text(
                    "✅ منوی شما به‌روز شد.\n"
                    "نیازی به ارسال پیام همگانی نیست — کاربران منوی جدید را به‌صورت خودکار در اولین استفاده‌ی بعدی می‌بینند.",
                    reply_markup=admin_main_menu(),
                )
        return

    # ── broken-proxy report: admin deactivates the proxy ──
    if data.startswith("rpt_off:"):
        pid = int(data.split(":", 1)[1])
        async with async_session() as s:
            p = await s.get(Proxy, pid)
            if p is None:
                await q.answer("پروکسی یافت نشد (شاید حذف شده).", show_alert=True)
                return
            p.is_active = False
            await s.commit()
        await q.answer("پروکسی غیرفعال شد 🔴", show_alert=True)
        return

    # ── broken-report reply: admin answers the reporting user directly ──
    if data.startswith("rpt_ok:") or data.startswith("rpt_fix:"):
        parts = data.split(":")
        kind = parts[0]
        pid = int(parts[1]) if len(parts) > 1 and parts[1].lstrip("-").isdigit() else None
        reporter = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else None
        if not reporter:
            await q.answer("شناسه کاربر گزارش‌دهنده در دسترس نیست.", show_alert=True)
            return
        plink = None
        async with async_session() as s:
            st = await get_settings(s)
            ok_tpl = (getattr(st, "report_ok_message", None) or "").strip() or DEFAULT_REPORT_OK
            fix_tpl = (getattr(st, "report_fix_message", None) or "").strip() or DEFAULT_REPORT_FIX
            if pid is not None:
                p = await s.get(Proxy, pid)
                if p:
                    plink = p.link
        if kind == "rpt_ok":
            body = ok_tpl
            markup = None
            if plink:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⚡️ اتصال دوباره", url=plink)]]
                )
            try:
                try:
                    await context.bot.send_message(reporter, body, parse_mode="HTML",
                                                   reply_markup=markup, disable_web_page_preview=True)
                except Exception:
                    await context.bot.send_message(reporter, body, reply_markup=markup,
                                                   disable_web_page_preview=True)
                await q.answer("به کاربر اطلاع داده شد: پروکسی سالم است ✅", show_alert=True)
            except Exception:
                await q.answer("ارسال به کاربر ناموفق بود (شاید ربات را بلاک کرده).", show_alert=True)
        else:  # rpt_fix
            # Re-subscribe the user to the 'new proxy ready' notification.
            async with async_session() as s:
                u = await s.get(User, reporter)
                if u:
                    u.wants_notify = True
                    await s.commit()
            body = fix_tpl
            try:
                try:
                    await context.bot.send_message(reporter, body, parse_mode="HTML",
                                                   disable_web_page_preview=True)
                except Exception:
                    await context.bot.send_message(reporter, body, disable_web_page_preview=True)
                await q.answer("به کاربر اطلاع داده شد: در حال رفع مشکل 🛠", show_alert=True)
            except Exception:
                await q.answer("ارسال به کاربر ناموفق بود (شاید ربات را بلاک کرده).", show_alert=True)
        return

    # ── broken-report reply: admin sends a CUSTOM free-text message to the user ──
    if data.startswith("rpt_msg:"):
        parts = data.split(":")
        reporter = int(parts[2]) if len(parts) > 2 and parts[2].lstrip("-").isdigit() else None
        if not reporter:
            await q.answer("شناسه کاربر گزارش‌دهنده در دسترس نیست.", show_alert=True)
            return
        context.user_data["await"] = "report_custom"
        context.user_data["report_target"] = reporter
        await q.answer()
        await q.message.reply_text(
            "پیام دلخواه خود را برای راهنمایی این کاربر بفرستید (HTML تلگرام پشتیبانی می‌شود).\n"
            "این پیام فقط به همین کاربر ارسال می‌شود.",
        )
        return

    # ── notify users about a newly added / replaced proxy ──
    if data.startswith("notify:"):
        _, scope, pid = data.split(":", 2)
        pid = int(pid)
        if scope == "no":
            await q.answer("باشه، اطلاع‌رسانی انجام نشد.")
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
        from sqlalchemy import select
        async with async_session() as s:
            if scope == "reporters":
                res = await s.execute(select(User).where(User.wants_notify == True))  # noqa: E712
            else:  # all
                res = await s.execute(select(User))
            targets = list(res.scalars().all())
        await q.answer(f"در حال ارسال به {len(targets)} کاربر...")
        sent = 0
        for u in targets:
            try:
                await context.bot.send_message(
                    u.chat_id,
                    "🔔 پروکسی جدید آماده است! برای دریافت، دکمه «دریافت پروکسی» را بزنید.",
                )
                sent += 1
            except Exception:
                pass
        # Clear the notify flag for reporters we just told.
        if scope == "reporters" and targets:
            async with async_session() as s:
                for u in targets:
                    row = await s.get(User, u.chat_id)
                    if row:
                        row.wants_notify = False
                await s.commit()
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            await q.message.reply_text(f"✅ اطلاع‌رسانی به {sent} کاربر انجام شد.")
        except Exception:
            pass
        return

    # ── selection strategy ──
    if data.startswith("strat:"):
        val = data.split(":", 1)[1]
        async with async_session() as s:
            st = await get_settings(s)
            st.selection_strategy = val
            await s.commit()
            await q.answer("روش انتخاب ذخیره شد ✅")
            await q.edit_message_reply_markup(reply_markup=selection_strategy_kb(val))
        return

    # ── rotation ──
    if data.startswith("rot:"):
        sub = data.split(":", 1)[1]
        async with async_session() as s:
            st = await get_settings(s)
            if sub == "manual":
                st.rotation_mode = "manual"
                await s.commit()
                await q.answer("چرخش دستی شد")
                await q.edit_message_reply_markup(reply_markup=rotation_kb("manual", st.rotation_hours or 0))
            elif sub == "auto":
                st.rotation_mode = "auto"
                if not st.rotation_hours:
                    st.rotation_hours = 6
                st.last_rotated_at = datetime.utcnow()
                await s.commit()
                await q.answer("چرخش خودکار فعال شد")
                await q.edit_message_reply_markup(reply_markup=rotation_kb("auto", st.rotation_hours))
            elif sub == "sethours":
                context.user_data["await"] = "rot_hours"
                await q.answer()
                await q.message.reply_text("بازه چرخش را به ساعت بفرستید (مثلاً 6):")
            elif sub == "now":
                # manual immediate rotate: advance pin to next active proxy
                from sqlalchemy import select
                res = await s.execute(
                    select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)  # noqa: E712
                )
                proxies = list(res.scalars().all())
                if not proxies:
                    await q.answer("پروکسی فعالی نیست.", show_alert=True)
                    return
                ids = [p.id for p in proxies]
                if st.pinned_proxy_id in ids:
                    idx = ids.index(st.pinned_proxy_id)
                    st.pinned_proxy_id = ids[(idx + 1) % len(ids)]
                else:
                    st.pinned_proxy_id = ids[0]
                st.last_rotated_at = datetime.utcnow()
                await s.commit()
                await q.answer("چرخش انجام شد ✅", show_alert=True)
        return

    # ── proxy ops ──
    if data == "px_add":
        from .keyboards import cancel_kb
        context.user_data["await"] = "proxy_link"
        await q.answer()
        await q.message.reply_text(
            "لینک پروکسی را بفرستید (تک لینک):\n"
            "مثال: https://t.me/proxy?server=1.2.3.4&port=443&secret=ee...\n\n"
            "برای لغو، روی «❌ انصراف» بزنید یا /cancel بفرستید.",
            reply_markup=cancel_kb(),
        )
        return
    if data.startswith("px_"):
        op, pid = data.split(":", 1)
        pid = int(pid)
        async with async_session() as s:
            p = await s.get(Proxy, pid)
            if p is None:
                await q.answer("پروکسی یافت نشد.", show_alert=True)
                return
            if op == "px_toggle":
                p.is_active = not p.is_active
                await s.commit()
                await q.answer("فعال شد 🟢" if p.is_active else "غیرفعال شد 🔴")
                st = await get_settings(s)
                from .handlers_admin import build_proxy_card
                txt, markup = await build_proxy_card(s, p, st)
                try:
                    await q.edit_message_text(txt, reply_markup=markup)
                except Exception:
                    pass
            elif op == "px_pin":
                st = await get_settings(s)
                st.pinned_proxy_id = pid
                await s.commit()
                await q.answer("این پروکسی پین شد 📌", show_alert=True)
                # Refresh THIS message so it clearly shows it's pinned.
                from .handlers_admin import build_proxy_card
                txt, markup = await build_proxy_card(s, p, st)
                try:
                    await q.edit_message_text(txt, reply_markup=markup)
                except Exception:
                    pass
            elif op == "px_del":
                st = await get_settings(s)
                if st.pinned_proxy_id == pid:
                    st.pinned_proxy_id = None
                # Drop the unique-user rows for this proxy too.
                from sqlalchemy import delete
                from .database import ProxyUser
                await s.execute(delete(ProxyUser).where(ProxyUser.proxy_id == pid))
                await s.delete(p)
                await s.commit()
                await q.answer("حذف شد 🗑")
                try:
                    await q.message.delete()
                except Exception:
                    pass
        return

    # ── promotional message controls ──
    if data == "promo_toggle":
        async with async_session() as s:
            st = await get_settings(s)
            st.promo_enabled = not getattr(st, "promo_enabled", False)
            await s.commit()
            enabled = st.promo_enabled
            position = getattr(st, "promo_position", "after")
        await q.answer("تبلیغ " + ("روشن شد 🟢" if enabled else "خاموش شد ⚪️"))
        try:
            await q.edit_message_reply_markup(reply_markup=promo_admin_kb(enabled, position))
        except Exception:
            pass
        return
    if data == "promo_pos":
        async with async_session() as s:
            st = await get_settings(s)
            cur = (getattr(st, "promo_position", "after") or "after").lower()
            new_pos = "before" if cur != "before" else "after"
            st.promo_position = new_pos
            await s.commit()
            enabled = getattr(st, "promo_enabled", False)
        await q.answer("نمایش تبلیغ: " + ("قبل از پروکسی 🔼" if new_pos == "before" else "بعد از پروکسی 🔽"))
        try:
            await q.edit_message_reply_markup(reply_markup=promo_admin_kb(enabled, new_pos))
        except Exception:
            pass
        return
    if data == "promo_set":
        context.user_data["await"] = "promo_message"
        await q.answer()
        await q.message.reply_text(
            "متن تبلیغاتی را بفرستید (HTML تلگرام پشتیبانی می‌شود):\n"
            "مثال: <b>حمایت از ما</b> — در کانال‌های زیر عضو شوید 🙏\n"
            "تگ‌های مجاز: &lt;b&gt; &lt;i&gt; &lt;u&gt; &lt;a href&gt; &lt;code&gt;",
            parse_mode="HTML",
        )
        return
    if data == "promo_count":
        context.user_data["await"] = "promo_count"
        await q.answer()
        await q.message.reply_text(
            "چند کانال اختیاری در هر بار به کاربر نشان داده شود؟ عدد بفرستید (مثلاً 3):"
        )
        return
    if data == "promo_preview":
        async with async_session() as s:
            st = await get_settings(s)
            msg = (st.promo_message or "").strip()
        if not msg:
            await q.answer("هنوز متنی تنظیم نشده.", show_alert=True)
            return
        await q.answer()
        try:
            await q.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            await q.message.reply_text(f"⚠️ HTML نامعتبر است: {e}\nمتن خام:\n{msg}")
        return

    # ── broadcast controls (manual + automatic) ──
    if data == "bc_manual":
        context.user_data["await"] = "broadcast_manual"
        await q.answer()
        await q.message.reply_text(
            "متن پیام همگانی را بفرستید (HTML تلگرام پشتیبانی می‌شود).\n"
            "این پیام بلافاصله به همه‌ی کاربران ارسال می‌شود.",
        )
        return
    if data == "bc_edit_last":
        context.user_data["await"] = "broadcast_edit"
        await q.answer()
        await q.message.reply_text(
            "متن اصلاح‌شدهی آخرین پیام همگانی را بفرستید (HTML تلگرام پشتیبانی می‌شود).\n"
            "همه‌ی نسخه‌هایی که از آخرین ارسال دستی برای کاربران رفته، ویرایش می‌شوند.",
        )
        return
    if data == "bc_auto_toggle":
        async with async_session() as s:
            st = await get_settings(s)
            st.broadcast_auto_enabled = not getattr(st, "broadcast_auto_enabled", False)
            if st.broadcast_auto_enabled:
                # Start the clock now so the first auto-send waits a full interval.
                st.broadcast_last_sent_at = datetime.utcnow()
            await s.commit()
            enabled = st.broadcast_auto_enabled
            hours = int(st.broadcast_auto_hours or 24)
            has_msg = bool((st.broadcast_auto_message or "").strip())
        if enabled and not has_msg:
            await q.answer("روشن شد، اما هنوز متنی تنظیم نشده! ابتدا متن خودکار را تنظیم کنید.", show_alert=True)
        else:
            await q.answer("ارسال خودکار " + ("روشن شد 🟢" if enabled else "خاموش شد ⚪️"))
        try:
            await q.edit_message_reply_markup(reply_markup=broadcast_admin_kb(enabled, hours))
        except Exception:
            pass
        return
    if data == "bc_auto_set":
        context.user_data["await"] = "broadcast_auto_message"
        await q.answer()
        await q.message.reply_text(
            "متن پیام خودکار را بفرستید (HTML تلگرام پشتیبانی می‌شود):",
        )
        return
    if data == "bc_auto_hours":
        await q.answer()
        await q.message.reply_text(
            "بازه ارسال خودکار را انتخاب کنید:",
            reply_markup=broadcast_interval_kb(),
        )
        return
    if data.startswith("bc_int:"):
        val = data.split(":", 1)[1]
        if val == "custom":
            context.user_data["await"] = "broadcast_hours"
            await q.answer()
            await q.message.reply_text("تعداد ساعت بین هر ارسال را بفرستید (مثلاً 36):")
            return
        hours = int(val)
        async with async_session() as s:
            st = await get_settings(s)
            st.broadcast_auto_hours = hours
            await s.commit()
        await q.answer(f"بازه روی هر {hours} ساعت تنظیم شد ✅", show_alert=True)
        try:
            await q.edit_message_reply_markup(reply_markup=broadcast_interval_kb())
        except Exception:
            pass
        return
    if data == "bc_auto_preview":
        async with async_session() as s:
            st = await get_settings(s)
            msg = (st.broadcast_auto_message or "").strip()
        if not msg:
            await q.answer("هنوز متنی تنظیم نشده.", show_alert=True)
            return
        await q.answer()
        try:
            await q.message.reply_text(msg, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            await q.message.reply_text(f"⚠️ HTML نامعتبر است: {e}\nمتن خام:\n{msg}")
        return

    # ── report-reply message templates (edit the two canned replies) ──
    if data == "rpm_set_ok":
        context.user_data["await"] = "report_msg_ok"
        await q.answer()
        await q.message.reply_text(
            "متن پیام «سالم است» را بفرستید (HTML تلگرام پشتیبانی می‌شود).\n"
            "این پیام وقتی که روی دکمه«✅ سالم است» بزنید به کاربر ارسال می‌شود.",
        )
        return
    if data == "rpm_set_fix":
        context.user_data["await"] = "report_msg_fix"
        await q.answer()
        await q.message.reply_text(
            "متن پیام «در حال رفع» را بفرستید (HTML تلگرام پشتیبانی می‌شود).\n"
            "این پیام وقتی که روی دکمه«🛠 در حال رفع» بزنید به کاربر ارسال می‌شود.",
        )
        return
    if data == "rpm_preview":
        async with async_session() as s:
            st = await get_settings(s)
            ok_msg = (getattr(st, "report_ok_message", None) or "").strip() or DEFAULT_REPORT_OK
            fix_msg = (getattr(st, "report_fix_message", None) or "").strip() or DEFAULT_REPORT_FIX
        await q.answer()
        for label, msg in (("✅ سالم است", ok_msg), ("🛠 در حال رفع", fix_msg)):
            try:
                await q.message.reply_text(f"‹{label}›\n\n{msg}", parse_mode="HTML",
                                           disable_web_page_preview=True)
            except Exception as e:
                await q.message.reply_text(f"⚠️ HTML نامعتبر است ({label}): {e}\n{msg}")
        return
    if data == "rpm_reset":
        async with async_session() as s:
            st = await get_settings(s)
            st.report_ok_message = None
            st.report_fix_message = None
            await s.commit()
        await q.answer("پیام‌ها به حالت پیش‌فرض بازگردانده شدند ♻️", show_alert=True)
        try:
            await q.edit_message_reply_markup(reply_markup=report_messages_kb())
        except Exception:
            pass
        return

    # ── per-channel description / logo config ──
    if data.startswith("chd_"):
        op, cid = data.split(":", 1)
        cid = int(cid)
        async with async_session() as s:
            ch = await s.get(Channel, cid)
            if ch is None:
                await q.answer("کانال یافت نشد.", show_alert=True)
                return
            if op == "chd_desc":
                ch.desc_enabled = not getattr(ch, "desc_enabled", False)
                await s.commit()
                await q.answer("توضیحات " + ("روشن شد 🟢" if ch.desc_enabled else "خاموش شد ⚪️"))
            elif op == "chd_logo":
                ch.logo_enabled = not getattr(ch, "logo_enabled", False)
                await s.commit()
                if ch.logo_enabled:
                    await q.answer("لوگوی کانال روشن شد 🟢 (عکس پروفایل کوچک کانال)", show_alert=True)
                else:
                    await q.answer("لوگوی کانال خاموش شد ⚪️")
            elif op == "chd_bio":
                ch.use_channel_bio = not getattr(ch, "use_channel_bio", False)
                if ch.use_channel_bio and not getattr(ch, "desc_enabled", False):
                    ch.desc_enabled = True
                await s.commit()
                if ch.use_channel_bio:
                    await q.answer(
                        "متن توضیحات از خود کانال گرفته می‌شود 🟢\n"
                        "نکته: برای خواندن توضیحات کانال، ربات باید عضو/ادمین آن کانال باشد.",
                        show_alert=True,
                    )
                else:
                    await q.answer("متن از خود کانال خاموش شد ⚪️ (از متن سفارشی شما استفاده می‌شود)")
            elif op == "chd_text":
                from .keyboards import cancel_kb
                context.user_data["await"] = "channel_text"
                context.user_data["channel_cfg_id"] = cid
                await q.answer()
                await q.message.reply_text(
                    "متن توضیحات این کانال را بفرستید (HTML تلگرام پشتیبانی می‌شود).\n"
                    "این متن بالای دکمه«عضویت» به کاربر نشان داده می‌شود.\n\n"
                    "برای لغو، روی «❌ انصراف» بزنید یا /cancel بفرستید.",
                    reply_markup=cancel_kb(),
                )
                return
            elif op == "chd_img":
                from .keyboards import cancel_kb
                context.user_data["await"] = "channel_img"
                context.user_data["channel_cfg_id"] = cid
                await q.answer()
                await q.message.reply_text(
                    "یک عکس برای این کانال بفرستید (به صورت عکس، نه فایل).\n"
                    "این عکس بالای متن تبلیغ کانال نمایش داده می‌شود.\n\n"
                    "برای لغو، روی «❌ انصراف» بزنید یا /cancel بفرستید.",
                    reply_markup=cancel_kb(),
                )
                return
            elif op == "chd_imgclr":
                ch.desc_image = None
                await s.commit()
                await q.answer("تصویر حذف شد ❌")
            elif op == "chd_prev":
                await q.answer()
                from .channel_promo import send_described_channel
                await send_described_channel(context.bot, q.from_user.id, ch)
                return
            # Refresh the config panel to reflect the new state.
            fresh = await s.get(Channel, cid)
        try:
            await q.edit_message_reply_markup(reply_markup=channel_config_kb(fresh))
        except Exception:
            pass
        return

    # ── channel ops ──
    if data == "fj_toggle":
        async with async_session() as s:
            st = await get_settings(s)
            st.force_join_enabled = not getattr(st, "force_join_enabled", True)
            await s.commit()
            from sqlalchemy import select
            res = await s.execute(select(Channel).order_by(Channel.id))
            channels = list(res.scalars().all())
            enabled = st.force_join_enabled
        await q.answer("اجبار عضویت " + ("روشن شد 🔔" if enabled else "خاموش شد 🔕"))
        try:
            await q.edit_message_reply_markup(reply_markup=channels_kb(channels, force_enabled=enabled))
        except Exception:
            pass
        return

    if data.startswith("ch_"):
        if data == "ch_add":
            from .keyboards import cancel_kb
            context.user_data["await"] = "channel_add"
            await q.answer()
            await q.message.reply_text(
                "شناسه کانال را بفرستید به صورت:\n`@username | عنوان`\n"
                "یا شناسه عددی: `-1001234567890 | عنوان`\n\n"
                "برای لغو، روی «❌ انصراف» بزنید یا /cancel بفرستید.",
                parse_mode="Markdown",
                reply_markup=cancel_kb(),
            )
            return
        if data == "ch_back":
            from sqlalchemy import select
            async with async_session() as s:
                res = await s.execute(select(Channel).order_by(Channel.id))
                channels = list(res.scalars().all())
                st = await get_settings(s)
                enabled = getattr(st, "force_join_enabled", True)
            await q.answer()
            try:
                await q.edit_message_text(
                    "📢 کانال‌های اسپانسر — روی نام کانال بزنید تا اجباری/اختیاری شود:",
                    reply_markup=channels_kb(channels, force_enabled=enabled),
                )
            except Exception:
                try:
                    await q.edit_message_reply_markup(reply_markup=channels_kb(channels, force_enabled=enabled))
                except Exception:
                    pass
            return
        op, cid = data.split(":", 1)
        cid = int(cid)
        async with async_session() as s:
            ch = await s.get(Channel, cid)
            if ch is None:
                await q.answer("کانال یافت نشد.", show_alert=True)
                return
            if op == "ch_cfg":
                await q.answer()
                desc_on = getattr(ch, "desc_enabled", False)
                logo_on = getattr(ch, "logo_enabled", False)
                bio_on = getattr(ch, "use_channel_bio", False)
                has_img = bool((getattr(ch, "desc_image", None) or "").strip())
                has_txt = bool((getattr(ch, "desc_html", None) or "").strip())
                text_src = "از خود کانال" if bio_on else ("سفارشی" if has_txt else "خالی")
                info = (
                    f"⚙️ تنظیمات کانال: {ch.title or ch.chat_id}\n\n"
                    f"• توضیحات: {'روشن 🟢' if desc_on else 'خاموش ⚪️'}\n"
                    f"• منبع متن: {text_src} | تصویر: {'دارد' if has_img else 'ندارد'}\n"
                    f"• لوگوی کانال: {'روشن 🟢' if logo_on else 'خاموش ⚪️'}\n\n"
                    "وقتی توضیحات روشن باشد، این کانال در یک پیام جداگانه با تصویر/لوگو و متن، "
                    "و یک دکمه عضویت نمایش داده می‌شود."
                )
                try:
                    await q.edit_message_text(info, reply_markup=channel_config_kb(ch))
                except Exception:
                    await q.message.reply_text(info, reply_markup=channel_config_kb(ch))
                return
            if op == "ch_toggle":
                ch.is_required = not ch.is_required
                await s.commit()
                await q.answer("وضعیت کانال تغییر کرد ✅")
            elif op == "ch_en":
                ch.is_enabled = not getattr(ch, "is_enabled", True)
                await s.commit()
                await q.answer("کانال " + ("فعال شد 🟢" if ch.is_enabled else "غیرفعال شد 🔴"))
            elif op == "ch_pin":
                ch.is_pinned = not getattr(ch, "is_pinned", False)
                await s.commit()
                await q.answer("پین " + ("شد 📌" if ch.is_pinned else "برداشته شد"))
            elif op == "ch_del":
                await s.delete(ch)
                await s.commit()
                await q.answer("کانال حذف شد 🗑")
            from sqlalchemy import select
            res = await s.execute(select(Channel).order_by(Channel.id))
            channels = list(res.scalars().all())
            st = await get_settings(s)
            enabled = getattr(st, "force_join_enabled", True)
        try:
            await q.edit_message_reply_markup(reply_markup=channels_kb(channels, force_enabled=enabled))
        except Exception:
            pass
        return
