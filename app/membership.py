"""Forced-join checking against required channels.

Real verification uses Telegram's getChatMember and therefore REQUIRES the bot
to be an administrator (or at least a member) of each required channel. If the
bot cannot read membership for a channel (not admin / private), that channel is
treated as 'cannot verify' and is skipped for the gate rather than blocking
everyone — this keeps the bot usable until the admin promotes it.
"""
from telegram.error import TelegramError
from sqlalchemy import select

from .database import Channel

_MEMBER_OK = {"member", "administrator", "creator", "owner"}


async def required_channels(session):
    res = await session.execute(
        select(Channel).where(Channel.is_required == True)  # noqa: E712
    )
    return list(res.scalars().all())


async def missing_channels(bot, session, user_id):
    """Return the list of required channels the user has NOT joined.

    Channels the bot cannot verify (not admin) are skipped so they don't block.
    """
    missing = []
    for ch in await required_channels(session):
        try:
            m = await bot.get_chat_member(ch.chat_id, user_id)
            status = getattr(m, "status", None)
            if status not in _MEMBER_OK:
                missing.append(ch)
        except TelegramError:
            # Bot not admin / channel unreadable -> cannot enforce, skip.
            continue
    return missing
