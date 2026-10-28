-- Reference schema (the bot auto-creates these via SQLAlchemy on startup).
-- Kept here for manual inspection / Neon SQL editor.

CREATE TABLE IF NOT EXISTS proxies (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(128) NOT NULL,
    link          TEXT NOT NULL,
    proxy_type    VARCHAR(16) DEFAULT 'mtproto',
    server        VARCHAR(255),
    port          INTEGER,
    secret        TEXT,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    served_count  INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_settings (
    id                 INTEGER PRIMARY KEY,
    selection_strategy VARCHAR(16) DEFAULT 'newest',
    pinned_proxy_id    INTEGER,
    rotation_mode      VARCHAR(16) DEFAULT 'manual',
    rotation_hours     INTEGER DEFAULT 0,
    last_rotated_at    TIMESTAMP,
    force_join_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    promo_enabled      BOOLEAN NOT NULL DEFAULT FALSE,
    promo_message      TEXT,
    promo_count        INTEGER NOT NULL DEFAULT 3,
    broadcast_auto_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    broadcast_auto_message TEXT,
    broadcast_auto_hours   INTEGER NOT NULL DEFAULT 24,
    broadcast_last_sent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    id           SERIAL PRIMARY KEY,
    chat_id      VARCHAR(128) NOT NULL,
    title        VARCHAR(255),
    invite_link  TEXT,
    is_required  BOOLEAN NOT NULL DEFAULT TRUE,
    shown_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    chat_id       BIGINT PRIMARY KEY,
    username      VARCHAR(255),
    is_admin      BOOLEAN DEFAULT FALSE,
    served_count  INTEGER NOT NULL DEFAULT 0,
    last_proxy_id INTEGER,
    wants_notify  BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen    TIMESTAMP DEFAULT NOW()
);

-- One row per (proxy, user) pair: used to count UNIQUE users per proxy.
CREATE TABLE IF NOT EXISTS proxy_users (
    id         SERIAL PRIMARY KEY,
    proxy_id   INTEGER NOT NULL,
    chat_id    BIGINT NOT NULL,
    first_used TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_proxy_user UNIQUE (proxy_id, chat_id)
);
CREATE INDEX IF NOT EXISTS ix_proxy_users_proxy_id ON proxy_users (proxy_id);

-- Append-only activity log (stats are derived from here; never deleted).
CREATE TABLE IF NOT EXISTS events (
    id          SERIAL PRIMARY KEY,
    event_type  VARCHAR(32) NOT NULL,
    chat_id     BIGINT,
    ref         VARCHAR(128),
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_events_type ON events (event_type);
CREATE INDEX IF NOT EXISTS ix_events_chat_id ON events (chat_id);
CREATE INDEX IF NOT EXISTS ix_events_created_at ON events (created_at);

-- Per-channel stats keyed by chat_id STRING, independent of `channels` so
-- deleting a channel does NOT erase its history.
CREATE TABLE IF NOT EXISTS channel_stats (
    chat_id      VARCHAR(128) PRIMARY KEY,
    title        VARCHAR(255),
    join_prompts INTEGER NOT NULL DEFAULT 0,
    promo_shows  INTEGER NOT NULL DEFAULT 0,
    joins        INTEGER NOT NULL DEFAULT 0,
    leaves       INTEGER NOT NULL DEFAULT 0,
    updated_at   TIMESTAMP DEFAULT NOW()
);

-- Singleton settings row
INSERT INTO bot_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
