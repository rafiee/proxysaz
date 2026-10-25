"""Admin inline-callback handlers: strategy, rotation, proxy & channel ops."""
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from .config import ADMIN_CHAT_IDS
from .database import async_session, get_settings, Proxy, Channel
from .keyboards import selection_strategy_kb, rotation_kb, channels_kb


def _is_admin(uid):
    return uid in ADMIN_CHAT_IDS


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not _is_admin(q.from_user.id):
        await q.answer("دسترسی ندارید.", show_alert=True)
        return
    data = q.data or ""

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
                await q.answer("وضعیت تغییر کرد ✅")
            elif op == "px_pin":
                st = await get_settings(s)
                st.pinned_proxy_id = pid
                await s.commit()
                await q.answer("این پروکسی پین شد 📌", show_alert=True)
            elif op == "px_del":
                st = await get_settings(s)
                if st.pinned_proxy_id == pid:
                    st.pinned_proxy_id = None
                await s.delete(p)
                await s.commit()
                await q.answer("حذف شد 🗑")
                try:
                    await q.message.delete()
                except Exception:
                    pass
        return

    # ── channel ops ──
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
        try:
            await q.edit_message_reply_markup(reply_markup=channels_kb(channels))
        except Exception:
            pass
        return
