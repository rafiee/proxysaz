"""Async SQLAlchemy models + lazy session for the Telegram proxy bot."""
import ssl as ssl_lib
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, select, text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from .config import DATABASE_URL, DB_REQUIRE_SSL

Base = declarative_base()


class Proxy(Base):
    __tablename__ = "proxies"
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)          # admin-only label
    link = Column(Text, nullable=False)                 # canonical t.me/proxy link
    proxy_type = Column(String(16), default="mtproto")  # mtproto | socks
    server = Column(String(255))
    port = Column(Integer)
    secret = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    served_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class BotSettings(Base):
    __tablename__ = "bot_settings"
    id = Column(Integer, primary_key=True)              # always 1 (singleton)
    selection_strategy = Column(String(16), default="newest")  # single|newest|spread
    pinned_proxy_id = Column(Integer, nullable=True)
    rotation_mode = Column(String(16), default="manual")       # manual|auto
    rotation_hours = Column(Integer, default=0)
    last_rotated_at = Column(DateTime, nullable=True)
    # Global master switch for the forced-join gate (independent of per-channel
    # is_required). When False, users get proxies without any join check.
    force_join_enabled = Column(Boolean, default=True, nullable=False)
    # Optional promotional (sponsor) message shown AFTER the proxy is delivered,
    # stored as Telegram-HTML. Shown together with buttons for OPTIONAL channels.
    promo_enabled = Column(Boolean, default=False, nullable=False)
    promo_message = Column(Text, nullable=True)
    # How many OPTIONAL (sponsor) channels to show the user at once, so a large
    # pool of channels is rotated instead of dumping them all (anti-boredom).
    promo_count = Column(Integer, default=3, nullable=False)
    # Where the promo block is shown relative to the delivered proxy:
    # 'after' (default) or 'before'.
    promo_position = Column(String(8), default="after", nullable=False)
    # ── Automatic broadcast ── a recurring message pushed to every user on a
    # fixed interval (half-day / daily / every other day, etc). Toggleable.
    broadcast_auto_enabled = Column(Boolean, default=False, nullable=False)
    broadcast_auto_message = Column(Text, nullable=True)     # Telegram-HTML
    broadcast_auto_hours = Column(Integer, default=24, nullable=False)
    broadcast_last_sent_at = Column(DateTime, nullable=True)
    # Editable reply templates for the broken-proxy report flow (Telegram-HTML).
    # When NULL, the code falls back to the defaults in app/texts.py.
    report_ok_message = Column(Text, nullable=True)
    report_fix_message = Column(Text, nullable=True)


class Event(Base):
    """Append-only activity log. Everything interesting the bot sees is written
    here as one row, so statistics never depend on a Channel/Proxy row still
    existing. Deleting a channel or proxy leaves its history untouched.

    event_type values used:
      start           user opened the bot (/start)
      request_proxy   user tapped 'Get proxy'
      proxy_served    a proxy link was actually delivered (ref = proxy id)
      join_gate_shown user was shown the forced-join screen
      recheck_click   user tapped 'I joined, check me'
      join_passed     user cleared the forced-join gate
      report_broken   user reported a proxy broken (ref = proxy id)
      promo_shown     sponsor/promo suggestion was shown to a user
      broadcast_sent  a broadcast message was delivered (ref = manual|auto)
    """
    __tablename__ = "events"
    id = Column(Integer, primary_key=True)
    event_type = Column(String(32), nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=True, index=True)   # the user involved
    ref = Column(String(128), nullable=True)                  # channel id / proxy id / mode
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class ChannelStat(Base):
    """Per-channel counters keyed by the channel's chat_id STRING, kept in a
    separate table from `channels`. This is deliberate: if the admin deletes a
    channel from the config, its historical stats (prompts shown, verified
    joins/leaves) are NOT lost — the bot keeps full history and functionality.
    """
    __tablename__ = "channel_stats"
    chat_id = Column(String(128), primary_key=True)
    title = Column(String(255), nullable=True)      # last-known title (cached)
    join_prompts = Column(Integer, default=0, nullable=False)   # times shown in join gate
    promo_shows = Column(Integer, default=0, nullable=False)    # times shown as sponsor
    joins = Column(Integer, default=0, nullable=False)          # verified joins (bot admin)
    leaves = Column(Integer, default=0, nullable=False)         # verified leaves (bot admin)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String(128), nullable=False)       # @username or -100...
    title = Column(String(255))
    invite_link = Column(Text, nullable=True)
    is_required = Column(Boolean, default=True, nullable=False)
    # How many times this channel has been shown as an optional/sponsor
    # suggestion. Used to rotate promo channels by least-shown-first.
    shown_count = Column(Integer, default=0, nullable=False)
    # ── Per-channel promotional description (works for BOTH required and
    # optional channels). When desc_enabled is True the channel is presented in
    # its own message: optional image/logo + HTML text + a Subscribe button,
    # instead of a plain button in the combined list.
    desc_enabled = Column(Boolean, default=False, nullable=False)
    desc_html = Column(Text, nullable=True)            # Telegram-HTML body/caption
    desc_image = Column(Text, nullable=True)           # uploaded photo file_id (or URL)
    logo_enabled = Column(Boolean, default=False, nullable=False)  # show channel avatar
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"
    chat_id = Column(BigInteger, primary_key=True)
    username = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False)
    served_count = Column(Integer, default=0, nullable=False)
    last_proxy_id = Column(Integer, nullable=True)
    # Set True when the user reports a broken proxy / wants to be told when a
    # fresh proxy is available; cleared after they are notified.
    wants_notify = Column(Boolean, default=False, nullable=False)
    first_seen = Column(DateTime, default=datetime.utcnow)


class ProxyUser(Base):
    """One row per (proxy, user) pair — lets us count UNIQUE users per proxy.

    Inserted the first time a given user is served a given proxy; the
    UniqueConstraint keeps it to one row per pair no matter how many times
    they request that same proxy again.
    """
    __tablename__ = "proxy_users"
    id = Column(Integer, primary_key=True)
    proxy_id = Column(Integer, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False)
    first_used = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("proxy_id", "chat_id", name="uq_proxy_user"),)


class BroadcastMessage(Base):
    """One row per delivered copy of a MANUAL broadcast, so the admin can edit
    the text afterwards (fix a typo) across every recipient. Rows are grouped
    by `batch_id`; the newest batch is the 'last broadcast' that edit targets.
    Old batches are pruned so this table never grows without bound.
    """
    __tablename__ = "broadcast_messages"
    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, nullable=False, index=True)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ─── Lazy engine/session (empty DATABASE_URL must not crash import) ───
_engine = None
_sessionmaker = None


def _build_engine():
    connect_args = {}
    if DB_REQUIRE_SSL:
        ctx = ssl_lib.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl_lib.CERT_NONE
        connect_args["ssl"] = ctx
    return create_async_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args=connect_args,
    )


def _get_sessionmaker():
    global _engine, _sessionmaker
    if _sessionmaker is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _engine = _build_engine()
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _sessionmaker


def async_session() -> AsyncSession:
    """Return a new AsyncSession (use as `async with async_session() as s:`)."""
    return _get_sessionmaker()()


# Lightweight additive migrations for columns added after first deploy.
# create_all() never ALTERs existing tables, so we add new columns here.
_MIGRATIONS = [
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS force_join_enabled BOOLEAN NOT NULL DEFAULT TRUE",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS promo_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS promo_message TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS wants_notify BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS promo_count INTEGER NOT NULL DEFAULT 3",
    "ALTER TABLE channels ADD COLUMN IF NOT EXISTS shown_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS broadcast_auto_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS broadcast_auto_message TEXT",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS broadcast_auto_hours INTEGER NOT NULL DEFAULT 24",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS broadcast_last_sent_at TIMESTAMP",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS report_ok_message TEXT",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS report_fix_message TEXT",
    "ALTER TABLE bot_settings ADD COLUMN IF NOT EXISTS promo_position VARCHAR(8) NOT NULL DEFAULT 'after'",
    "ALTER TABLE channels ADD COLUMN IF NOT EXISTS desc_enabled BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE channels ADD COLUMN IF NOT EXISTS desc_html TEXT",
    "ALTER TABLE channels ADD COLUMN IF NOT EXISTS desc_image TEXT",
    "ALTER TABLE channels ADD COLUMN IF NOT EXISTS logo_enabled BOOLEAN NOT NULL DEFAULT FALSE",
]


async def init_db():
    """Create tables if missing and ensure the singleton settings row exists."""
    sm = _get_sessionmaker()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in _MIGRATIONS:
            await conn.execute(text(stmt))
    async with sm() as s:
        row = await s.get(BotSettings, 1)
        if row is None:
            s.add(BotSettings(id=1))
            await s.commit()


async def get_settings(session) -> BotSettings:
    row = await session.get(BotSettings, 1)
    if row is None:
        row = BotSettings(id=1)
        session.add(row)
        await session.commit()
    return row
