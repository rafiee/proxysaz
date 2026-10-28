"""Rendering of channels to the user.

A channel can be shown two ways:
  * plain  — just a button in a combined keyboard (the classic behaviour);
  * described — its OWN message with an optional image / avatar, an HTML text,
    and a single Subscribe button underneath.

This module builds both the forced-join gate and the sponsor/promo block out of
those two shapes, so a described channel looks like a little promo card while
plain channels stay compact.

Telegram note: a message shows a photo at a fixed, standard size — there is no
API to force a 'tiny inline logo'. The channel AVATAR is small/low-res, so using
it (logo toggle) gives the most compact, badge-like look available.
"""
import logging

from .keyboards import (
    join_channels_kb, promo_channels_kb, recheck_only_kb, subscribe_button,
)
from .membership import _api_chat_id

log = logging.getLogger("proxy-bot.channel_promo")


def _resolve_url(ch, invite_fallback=None):
    """Best-effort public URL for a channel's Subscribe button."""
    url = getattr(ch, "invite_link", None)
    if url:
        return url
    cid = str(ch.chat_id).strip()
    if cid.startswith("@"):
        return f"https://t.me/{cid[1:]}"
    if cid.startswith("https://t.me/"):
        return cid
    if not cid.startswith("-") and not cid.lstrip("-").isdigit():
        return f"https://t.me/{cid.lstrip('@')}"
    return invite_fallback


async def _logo_file_id(bot, ch):
    """Return the channel's small (badge-size) avatar as raw bytes, or None.

    We DOWNLOAD the avatar and re-send the bytes instead of passing the
    profile-photo file_id straight to send_photo: Telegram often rejects a
    chat-photo file_id in sendPhoto ("wrong file identifier"), which is why the
    logo looked empty before. Bytes always work.
    """
    try:
        chat = await bot.get_chat(_api_chat_id(ch.chat_id))
        photo = getattr(chat, "photo", None)
        if photo is None:
            return None
        file_id = getattr(photo, "small_file_id", None) or getattr(photo, "big_file_id", None)
        if not file_id:
            return None
        tg_file = await bot.get_file(file_id)
        data = await tg_file.download_as_bytearray()
        return bytes(data) if data else None
    except Exception as e:
        log.warning("logo fetch failed for %s: %s", ch.chat_id, e)
        return None


async def _channel_bio(bot, ch):
    """Fetch the channel's own description/bio live via get_chat, or None."""
    try:
        chat = await bot.get_chat(_api_chat_id(ch.chat_id))
        return (getattr(chat, "description", None) or getattr(chat, "bio", None) or "").strip() or None
    except Exception as e:
        log.warning("bio fetch failed for %s: %s", ch.chat_id, e)
        return None


async def send_described_channel(bot, chat_id, ch):
    """Send one channel's rich promo card: optional avatar + optional image +
    HTML text (custom or the channel's own bio) + a Subscribe button."""
    url = _resolve_url(ch)
    kb = subscribe_button(url, ch.title) if url else None

    # Text source: the channel's own bio (if that toggle is on) or custom HTML.
    body = ""
    if getattr(ch, "use_channel_bio", False):
        body = (await _channel_bio(bot, ch)) or ""
    if not body.strip():
        body = (getattr(ch, "desc_html", None) or "").strip()
    if not body.strip():
        body = ch.title or str(ch.chat_id)

    image = (getattr(ch, "desc_image", None) or "").strip()
    logo = await _logo_file_id(bot, ch) if getattr(ch, "logo_enabled", False) else None

    async def _send_photo(file_ref, caption, markup):
        try:
            await bot.send_photo(chat_id, file_ref, caption=caption,
                                 parse_mode="HTML", reply_markup=markup)
            return True
        except Exception:
            try:
                await bot.send_photo(chat_id, file_ref, caption=caption, reply_markup=markup)
                return True
            except Exception as e:
                log.warning("send_photo failed for %s: %s", ch.chat_id, e)
                return False

    # Both a custom image and the avatar: show the small avatar as a lead-in,
    # then the main image card. One photo per message is a Telegram limit.
    if image and logo:
        await _send_photo(logo, None, None)
        if await _send_photo(image, body, kb):
            return
    elif image:
        if await _send_photo(image, body, kb):
            return
    elif logo:
        if await _send_photo(logo, body, kb):
            return

    # Text-only fallback (no image, or photo send failed).
    try:
        await bot.send_message(chat_id, body, parse_mode="HTML",
                               disable_web_page_preview=True, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id, body, disable_web_page_preview=True, reply_markup=kb)


def _split(channels):
    described = [c for c in channels if getattr(c, "desc_enabled", False)]
    plain = [c for c in channels if not getattr(c, "desc_enabled", False)]
    return described, plain


async def render_join_gate(bot, chat_id, channels):
    """Forced-join gate: described channels as cards + plain ones in a combined
    keyboard. Exactly ONE intro/instruction message carries the final
    'I joined, check me' control — no duplicate text line above it."""
    described, plain = _split(channels)
    # Described channels show up first as their own promo cards (each already
    # has a Subscribe button), then a SINGLE message carries the instruction
    # text plus the join/recheck keyboard.
    for ch in described:
        await send_described_channel(bot, chat_id, ch)
    if plain:
        await bot.send_message(
            chat_id,
            "برای دریافت پروکسی، ابتدا در کانال‌های زیر عضو شوید و سپس تایید کنید:",
            reply_markup=join_channels_kb(plain),
        )
    else:
        await bot.send_message(
            chat_id,
            "برای دریافت پروکسی، پس از عضویت در کانال‌های بالا دکمه زیر را بزنید:",
            reply_markup=recheck_only_kb(),
        )


async def render_promo(bot, chat_id, channels, header_html):
    """Sponsor/promo block: a header (the promo message), plain channels as a
    combined button list, and described channels as their own promo cards."""
    described, plain = _split(channels)
    body = (header_html or "").strip() or "برای حمایت از اسپانسرها، می‌توانید در کانال‌های زیر عضو شوید 🙏"
    if plain:
        try:
            await bot.send_message(chat_id, body, parse_mode="HTML",
                                   disable_web_page_preview=True,
                                   reply_markup=promo_channels_kb(plain))
        except Exception:
            await bot.send_message(chat_id, body, disable_web_page_preview=True,
                                   reply_markup=promo_channels_kb(plain))
    elif described:
        # No plain buttons, but there are cards: show the header on its own.
        try:
            await bot.send_message(chat_id, body, parse_mode="HTML",
                                   disable_web_page_preview=True)
        except Exception:
            await bot.send_message(chat_id, body, disable_web_page_preview=True)
    for ch in described:
        await send_described_channel(bot, chat_id, ch)
