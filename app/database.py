"""Async SQLAlchemy models + lazy session for the Telegram proxy bot."""
import ssl as ssl_lib
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    select, text,
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


class Channel(Base):
    __tablename__ = "channels"
    id = Column(Integer, primary_key=True)
    chat_id = Column(String(128), nullable=False)       # @username or -100...
    title = Column(String(255))
    invite_link = Column(Text, nullable=True)
    is_required = Column(Boolean, default=True, nullable=False)
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
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS wants_notify BOOLEAN NOT NULL DEFAULT FALSE",
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
