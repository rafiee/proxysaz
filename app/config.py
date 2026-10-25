"""Configuration + Neon/asyncpg DATABASE_URL normalization."""
import os
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Comma-separated list of admin Telegram chat IDs, e.g. "12345,67890"
_admin_raw = os.getenv("ADMIN_CHAT_IDS", "").strip()
ADMIN_CHAT_IDS = [
    int(x) for x in _admin_raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit()
]


def _normalize_db_url(raw: str) -> str:
    """Turn a Neon/standard Postgres URL into an asyncpg-compatible SQLAlchemy URL.

    - postgres:// or postgresql://  ->  postgresql+asyncpg://
    - drops libpq-only query params (sslmode, channel_binding, etc.) that
      asyncpg does NOT accept; SSL is handled via engine connect_args instead.
    """
    if not raw:
        return ""
    raw = raw.strip()
    parts = urlsplit(raw)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    elif scheme == "postgresql+psycopg2":
        scheme = "postgresql+asyncpg"

    # Strip query params asyncpg can't parse.
    drop = {"sslmode", "channel_binding", "options", "target_session_attrs"}
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k not in drop]
    query = urlencode(kept)

    return urlunsplit((scheme, parts.netloc, parts.path, query, parts.fragment))


# Whether the original URL requested SSL (Neon always does).
_raw_db = os.getenv("DATABASE_URL", "").strip()
DB_REQUIRE_SSL = (
    "sslmode=require" in _raw_db
    or "sslmode=verify" in _raw_db
    or ".neon.tech" in _raw_db
    or "aivencloud.com" in _raw_db
)
DATABASE_URL = _normalize_db_url(_raw_db)

# How many proxy connect-links a user may request before a soft cooldown note.
DEFAULT_SELECTION_STRATEGY = os.getenv("DEFAULT_SELECTION_STRATEGY", "newest")
