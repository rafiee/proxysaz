"""Proxy selection + rotation logic.

Selection strategies (no randomness):
  - single : always the pinned proxy (or the oldest active as fallback)
  - newest : the most recently added active proxy
  - spread : the active proxy with the LOWEST served_count (least-served first;
             ties broken by id so it is deterministic)

Rotation (only meaningful for the 'single' strategy, which otherwise stays on
one pinned proxy):
  - manual : admin pins / rotates by hand
  - auto   : every `rotation_hours`, advance the pin to the next active proxy
             (round-robin by id). 'newest' and 'spread' already move on their
             own, so auto-rotation simply re-pins for 'single'.
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from .database import Proxy, get_settings, ProxyUser


async def _active_proxies(session):
    res = await session.execute(
        select(Proxy).where(Proxy.is_active == True).order_by(Proxy.id)  # noqa: E712
    )
    return list(res.scalars().all())


async def maybe_auto_rotate(session):
    """Advance the pinned proxy if auto rotation is due. Returns the settings row."""
    st = await get_settings(session)
    if st.rotation_mode != "auto" or not st.rotation_hours:
        return st
    now = datetime.utcnow()
    due = (
        st.last_rotated_at is None
        or now - st.last_rotated_at >= timedelta(hours=st.rotation_hours)
    )
    if not due:
        return st
    proxies = await _active_proxies(session)
    if not proxies:
        return st
    ids = [p.id for p in proxies]
    if st.pinned_proxy_id in ids:
        idx = ids.index(st.pinned_proxy_id)
        st.pinned_proxy_id = ids[(idx + 1) % len(ids)]
    else:
        st.pinned_proxy_id = ids[0]
    st.last_rotated_at = now
    await session.commit()
    return st


async def pick_proxy(session, exclude_id=None):
    """Choose one active proxy per the configured strategy. Returns Proxy or None.

    exclude_id: if given and more than one active proxy exists, avoid returning
    that proxy (used for 'get another' / broken-report retries).
    """
    st = await maybe_auto_rotate(session)
    proxies = await _active_proxies(session)
    if not proxies:
        return None

    if exclude_id is not None:
        others = [p for p in proxies if p.id != exclude_id]
        if others:
            proxies = others

    strat = st.selection_strategy or "newest"

    if strat == "single":
        if st.pinned_proxy_id:
            for p in proxies:
                if p.id == st.pinned_proxy_id:
                    return p
        return proxies[0]  # fallback: oldest active

    if strat == "newest":
        return max(proxies, key=lambda p: p.id)

    if strat == "spread":
        # least-served first; deterministic tie-break by id
        return min(proxies, key=lambda p: (p.served_count, p.id))

    return proxies[0]


async def pick_promo_channels(session, candidates, n):
    """Pick at most N sponsor channels to show now, rotating the whole pool.

    Selection is least-shown-first (deterministic tie-break by id), then the
    chosen channels' shown_count is incremented and committed. Over many
    deliveries this cycles through ALL optional channels evenly instead of
    always showing the same few, so users don't get bored.
    """
    if not candidates:
        return []
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return []
    ordered = sorted(candidates, key=lambda c: (c.shown_count or 0, c.id))
    chosen = ordered[:n]
    for c in chosen:
        c.shown_count = (c.shown_count or 0) + 1
    await session.commit()
    return chosen


async def mark_served(session, proxy, user=None):
    proxy.served_count = (proxy.served_count or 0) + 1
    if user is not None:
        user.served_count = (user.served_count or 0) + 1
        user.last_proxy_id = proxy.id
        # Record a unique (proxy, user) pair the first time only, so we can
        # count how many DISTINCT users have used/clicked this proxy.
        existing = await session.execute(
            select(ProxyUser.id).where(
                ProxyUser.proxy_id == proxy.id,
                ProxyUser.chat_id == user.chat_id,
            )
        )
        if existing.scalar() is None:
            session.add(ProxyUser(proxy_id=proxy.id, chat_id=user.chat_id))
    await session.commit()
