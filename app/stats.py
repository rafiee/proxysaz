"""Activity logging + statistics aggregation.

All counters are derived from the append-only `events` table and the
`channel_stats` table, both of which are independent of the `channels` and
`proxies` config rows. Deleting a channel or proxy therefore never erases the
history or breaks these stats.
"""
from datetime import datetime, timedelta
from html import escape

from sqlalchemy import select, func

from .database import Event, ChannelStat, User, Proxy, Channel


async def log_event(session, event_type, chat_id=None, ref=None, commit=True):
    """Append one event row. `ref` is stringified (channel id / proxy id / mode)."""
    session.add(Event(
        event_type=event_type,
        chat_id=chat_id,
        ref=None if ref is None else str(ref),
    ))
    if commit:
        await session.commit()


async def _get_channel_stat(session, chat_id, title=None):
    cs = await session.get(ChannelStat, str(chat_id))
    if cs is None:
        cs = ChannelStat(chat_id=str(chat_id), title=title)
        session.add(cs)
    elif title and cs.title != title:
        cs.title = title
    return cs


async def bump_channel_stat(session, chat_id, field, title=None, delta=1, commit=True):
    """Increment one counter on a channel's persistent stats row.

    field in {'join_prompts','promo_shows','joins','leaves'}.
    """
    cs = await _get_channel_stat(session, chat_id, title=title)
    setattr(cs, field, (getattr(cs, field) or 0) + delta)
    cs.updated_at = datetime.utcnow()
    if commit:
        await session.commit()


async def _count_events(session, event_type, since=None, distinct_users=False):
    if distinct_users:
        q = select(func.count(func.distinct(Event.chat_id))).where(
            Event.event_type == event_type
        )
    else:
        q = select(func.count()).select_from(Event).where(
            Event.event_type == event_type
        )
    if since is not None:
        q = q.where(Event.created_at >= since)
    return (await session.execute(q)).scalar() or 0


async def gather_stats(session):
    """Return a dict of all the headline numbers the stats view renders."""
    now = datetime.utcnow()
    d1 = now - timedelta(days=1)
    d7 = now - timedelta(days=7)

    total_users = (await session.execute(
        select(func.count()).select_from(User)
    )).scalar() or 0

    n_proxies = (await session.execute(
        select(func.count()).select_from(Proxy)
    )).scalar() or 0
    n_active = (await session.execute(
        select(func.count()).select_from(Proxy).where(Proxy.is_active == True)  # noqa: E712
    )).scalar() or 0

    # Per-channel stats, persistent even for channels that were deleted.
    cs_rows = list((await session.execute(
        select(ChannelStat).order_by(ChannelStat.join_prompts.desc())
    )).scalars().all())
    # Which channels still exist in config (to flag deleted ones).
    live_ids = set((await session.execute(select(Channel.chat_id))).scalars().all())

    channels = []
    for cs in cs_rows:
        channels.append({
            "chat_id": cs.chat_id,
            "title": cs.title or cs.chat_id,
            "join_prompts": cs.join_prompts or 0,
            "promo_shows": cs.promo_shows or 0,
            "joins": cs.joins or 0,
            "leaves": cs.leaves or 0,
            "deleted": cs.chat_id not in live_ids,
        })

    return {
        "total_users": total_users,
        "n_proxies": n_proxies,
        "n_active": n_active,
        # lifetime / 24h / 7d event counts
        "started": await _count_events(session, "start", distinct_users=True),
        "started_24h": await _count_events(session, "start", since=d1, distinct_users=True),
        "started_7d": await _count_events(session, "start", since=d7, distinct_users=True),
        "requesters": await _count_events(session, "request_proxy", distinct_users=True),
        "requests": await _count_events(session, "request_proxy"),
        "requests_24h": await _count_events(session, "request_proxy", since=d1),
        "served": await _count_events(session, "proxy_served"),
        "served_24h": await _count_events(session, "proxy_served", since=d1),
        "gate_shown": await _count_events(session, "join_gate_shown"),
        "recheck_clicks": await _count_events(session, "recheck_click"),
        "join_passed": await _count_events(session, "join_passed", distinct_users=True),
        "promo_shown": await _count_events(session, "promo_shown"),
        "reports": await _count_events(session, "report_broken"),
        "reporters": await _count_events(session, "report_broken", distinct_users=True),
        "broadcasts": await _count_events(session, "broadcast_sent"),
        "channels": channels,
    }


def render_stats(s) -> str:
    """Render the stats dict into a Persian HTML report string."""
    lines = [
        "📊 <b>آمار کامل ربات</b>",
        "",
        "👥 <b>کاربران</b>",
        f"• کل کاربران ثبت‌شده: <b>{s['total_users']}</b>",
        f"• شروع ربات (/start): <b>{s['started']}</b>  "
        f"(۲۴ساعت: {s['started_24h']} | ۷روز: {s['started_7d']})",
        "",
        "🚀 <b>درخواست پروکسی</b>",
        f"• کاربرانی که درخواست دادند: <b>{s['requesters']}</b>",
        f"• کل درخواست‌ها: <b>{s['requests']}</b>  (۲۴ساعت: {s['requests_24h']})",
        f"• پروکسی تحویل‌داده‌شده: <b>{s['served']}</b>  (۲۴ساعت: {s['served_24h']})",
        f"• پروکسی‌ها: <b>{s['n_proxies']}</b> (فعال: {s['n_active']})",
        "",
        "🔔 <b>عضویت اجباری</b>",
        f"• دفعات نمایش صفحه عضویت: <b>{s['gate_shown']}</b>",
        f"• فشردن «عضو شدم، بررسی کن»: <b>{s['recheck_clicks']}</b>",
        f"• کاربرانی که از گیت عبور کردند: <b>{s['join_passed']}</b>",
        "",
        "📢 <b>تبلیغ / گزارش / پیام همگانی</b>",
        f"• نمایش پیشنهاد اسپانسر: <b>{s['promo_shown']}</b>",
        f"• گزارش پروکسی خراب: <b>{s['reports']}</b> (کاربر یکتا: {s['reporters']})",
        f"• پیام همگانی ارسال‌شده: <b>{s['broadcasts']}</b>",
    ]

    chans = s.get("channels") or []
    if chans:
        lines.append("")
        lines.append("📈 <b>آمار به تفکیک کانال</b> (شامل کانال‌های حذف‌شده)")
        for c in chans:
            tag = " 🗑(حذف‌شده)" if c["deleted"] else ""
            lines.append(
                f"• <b>{escape(str(c['title']))}</b>{tag}\n"
                f"   نمایش عضویت: {c['join_prompts']} | نمایش تبلیغ: {c['promo_shows']} | "
                f"عضو شد: {c['joins']} | ترک کرد: {c['leaves']}"
            )
        lines.append("")
        lines.append(
            "ℹ️ «عضو شد/ترک کرد» فقط برای کانال‌هایی شمارش می‌شود که ربات در آن‌ها ادمین است."
        )
    return "\n".join(lines)
