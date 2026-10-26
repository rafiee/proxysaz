"""Forced-join checking against required channels.

Real verification uses Telegram's getChatMember and therefore REQUIRES the bot
to be an administrator (or at least a member) of each required channel. If the
bot cannot read membership for a channel (not admin / private), that channel is
treated as 'cannot verify' and is skipped for the gate rather than blocking
everyone — this keeps the bot usable until the admin promotes it.
"""
from telegram.error import TelegramError
from sqlalchemy import select

from .database import Channel, get_settings

_MEMBER_OK = {"member", "administrator", "creator", "owner"}


def _api_chat_id(raw):
    """Normalize a stored channel id into something get_chat_member accepts.

    Telegram needs either a numeric id (e.g. -100123...) or an @username.
    Admins sometimes save a bare 'mychannel' without the leading '@', which
    makes the membership lookup fail and (wrongly) keep showing a channel the
    user already joined. Prefix '@' for bare usernames so verification works.
    """
    s = str(raw).strip()
    if not s:
        return s
    if s.startswith("@") or s.startswith("-") or s.lstrip("-").isdigit():
        return s
    if s.startswith("https://t.me/"):
        s = s.rsplit("/", 1)[-1]
    return "@" + s.lstrip("@")


async def required_channels(session):
    res = await session.execute(
        select(Channel).where(Channel.is_required == True)  # noqa: E712
    )
    return list(res.scalars().all())


async def optional_channels(session):
    """Channels marked NOT required — shown as sponsor/promo suggestions."""
    res = await session.execute(
        select(Channel).where(Channel.is_required == False)  # noqa: E712
    )
    return list(res.scalars().all())


async def unjoined_optional_channels(bot, session, user_id):
    """Optional (sponsor) channels the user has NOT joined yet.

    Only channels still worth suggesting are returned. A channel the bot
    cannot verify (not admin / private) is INCLUDED (we can't confirm the
    user is in it, so the sponsor still deserves exposure). If the user is
    already a confirmed member of every optional channel, this returns [] —
    the caller can then skip the promo entirely (nothing left to join).
    """
    result = []
    for ch in await optional_channels(session):
        try:
            m = await bot.get_chat_member(_api_chat_id(ch.chat_id), user_id)
            status = getattr(m, "status", None)
            if status in _MEMBER_OK:
                continue  # confirmed member -> never suggest it again
            # Explicitly left / kicked -> definitely still worth suggesting.
        except Exception:
            # Bot can't read membership for this channel (not admin / private).
            # We cannot confirm the user joined, so keep suggesting it.
            pass
        result.append(ch)
    return result


async def missing_channels(bot, session, user_id):
    """Return the list of required channels the user has NOT joined.

    Channels the bot cannot verify (not admin) are skipped so they don't block.
    If the global force-join switch is OFF, returns [] (no gate).
    """
    st = await get_settings(session)
    if not getattr(st, "force_join_enabled", True):
        return []
    missing = []
    for ch in await required_channels(session):
        try:
            m = await bot.get_chat_member(_api_chat_id(ch.chat_id), user_id)
            status = getattr(m, "status", None)
            if status not in _MEMBER_OK:
                missing.append(ch)
        except TelegramError:
            # Bot not admin / channel unreadable -> cannot enforce, skip.
            continue
    return missing
