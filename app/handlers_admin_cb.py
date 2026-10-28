"""Admin inline-callback handlers: strategy, rotation, proxy & channel ops."""
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, get_settings, Proxy, Channel, User
from .keyboards import (
    selection_strategy_kb, rotation_kb, channels_kb, promo_admin_kb, admin_proxy_row,
    broadcast_admin_kb, broadcast_interval_kb,
)
from .broadcast import do_broadcast


def _is_admin(uid):
    return uid in ADMIN_CHAT_IDS


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_admin(q.from_user.id):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return
    data = q.data or ""

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
            if pid is not None:
                p = await s.get(Proxy, pid)
                if p:
                    plink = p.link
        if kind == "rpt_ok":
            body = (
                "✅ پروکسی شما بررسی شد و سالم است.\n"
                "لطفاً اتصال اینترنت و اپ تلگرام خود را بررسی کنید و دوباره وصل شوید."
            )
            markup = None
            if plink:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                markup = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("⚡️ اتصال دوباره", url=plink)]]
                )
            try:
                await context.bot.send_message(reporter, body, reply_markup=markup)
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
            body = (
                "🛠 گزارش شما بررسی شد. مشکل به‌زودی برطرف می‌شود.\n"
                "به‌محض آماده‌شدن پروکسی جدید، به شما اطلاع می‌دهیم. ممنون از گزارش شما 🙏"
            )
            try:
                await context.bot.send_message(reporter, body)
                await q.answer("به کاربر اطلاع داده شد: در حال رفع مشکل 🛠", show_alert=True)
            except Exception:
                await q.answer("ارسال به کاربر ناموفق بود (شاید ربات را بلاک کرده).", show_alert=True)
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
        await q.answer("تبلیغ " + ("روشن شد 🟢" if enabled else "خاموش شد ⚪️"))
        try:
            await q.edit_message_reply_markup(reply_markup=promo_admin_kb(enabled))
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
            context.user_data["await"] = "channel_add"
            await q.answer()
            await q.message.reply_text(
                "شناسه کانال را بفرستید به صورت:\n`@username | عنوان`\n"
                "یا شناسه عددی: `-1001234567890 | عنوان`",
                parse_mode="Markdown",
            )
            return
        op, cid = data.split(":", 1)
        cid = int(cid)
        async with async_session() as s:
            ch = await s.get(Channel, cid)
            if ch is None:
                await q.answer("کانال یافت نشد.", show_alert=True)
                return
            if op == "ch_toggle":
                ch.is_required = not ch.is_required
                await s.commit()
                await q.answer("وضعیت کانال تغییر کرد ✅")
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
