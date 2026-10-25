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
    last_rotated_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channels (
    id           SERIAL PRIMARY KEY,
    chat_id      VARCHAR(128) NOT NULL,
    title        VARCHAR(255),
    invite_link  TEXT,
    is_required  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    chat_id       BIGINT PRIMARY KEY,
    username      VARCHAR(255),
    is_admin      BOOLEAN DEFAULT FALSE,
    served_count  INTEGER NOT NULL DEFAULT 0,
    last_proxy_id INTEGER,
    first_seen    TIMESTAMP DEFAULT NOW()
);

-- Singleton settings row
INSERT INTO bot_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;
