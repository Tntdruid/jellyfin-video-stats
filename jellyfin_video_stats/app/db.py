import json
import sqlite3
import threading
from typing import Optional

from config import DB_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    item_id          TEXT PRIMARY KEY,
    type             TEXT,              -- Movie | Episode
    name             TEXT,
    series_id        TEXT,
    series_name      TEXT,
    season_number    INTEGER,
    episode_number   INTEGER,
    year             INTEGER,
    genres           TEXT NOT NULL DEFAULT '[]',  -- JSON list
    studios          TEXT NOT NULL DEFAULT '[]',  -- JSON list
    people           TEXT NOT NULL DEFAULT '[]',  -- JSON list of {id, name, type, role}
    official_rating  TEXT,
    community_rating REAL,
    duration         REAL,
    fetched_at       INTEGER
);

CREATE TABLE IF NOT EXISTS plays (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           TEXT NOT NULL,
    user_id           TEXT,
    user_name         TEXT,
    client            TEXT,
    device            TEXT,
    started_at        INTEGER NOT NULL,  -- unix seconds, UTC
    ended_at          INTEGER NOT NULL,
    watched           REAL NOT NULL,     -- seconds actually played (pauses excluded)
    duration          REAL,              -- runtime in seconds
    progress          REAL,              -- furthest position reached, 0-1
    counted           INTEGER NOT NULL,  -- 1 = real viewing, 0 = only peeked
    completed         INTEGER NOT NULL,  -- 1 = watched to (nearly) the end
    play_method       TEXT,              -- DirectPlay | DirectStream | Transcode
    video_codec       TEXT,
    height            INTEGER,
    audio_lang        TEXT,
    subtitle_lang     TEXT,
    transcode_reasons TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_plays_started ON plays(started_at);
CREATE INDEX IF NOT EXISTS idx_plays_item ON plays(item_id);
CREATE INDEX IF NOT EXISTS idx_plays_user ON plays(user_id);
CREATE INDEX IF NOT EXISTS idx_items_series ON items(series_id);

-- every episode a series has in the library (not just the watched ones), for progress
CREATE TABLE IF NOT EXISTS series_episodes (
    item_id        TEXT PRIMARY KEY,
    series_id      TEXT NOT NULL,
    season_number  INTEGER,
    episode_number INTEGER,
    name           TEXT,
    duration       REAL
);
CREATE INDEX IF NOT EXISTS idx_series_episodes ON series_episodes(series_id);

CREATE TABLE IF NOT EXISTS series_info (
    series_id    TEXT PRIMARY KEY,
    name         TEXT,
    status       TEXT,     -- Continuing | Ended, as Jellyfin has it
    refreshed_at INTEGER   -- 0 = refresh soon
);

-- Jellyfin's own "played" mark per user, which also covers what was watched before the add-on or marked by hand
CREATE TABLE IF NOT EXISTS episode_played (
    user_id     TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    last_played INTEGER,
    PRIMARY KEY (user_id, item_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# columns added after 0.1.0; existing databases get them on start
MIGRATIONS = [
    ("plays", "source", "TEXT"),  # NULL = recorded by the collector, 'playback_reporting' = imported
]

DB_NAME = "video_stats.db"
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def connect() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_DIR / DB_NAME, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            existing = {r["name"] for r in _conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                _conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        _conn.commit()
    return _conn


def get_meta(key: str) -> Optional[str]:
    rows = query("SELECT value FROM meta WHERE key = ?", [key])
    return rows[0]["value"] if rows else None


def set_meta(key: str, value: str) -> None:
    execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            [key, value])


def query(sql: str, params=()) -> list:
    with _lock:
        return [dict(r) for r in connect().execute(sql, params).fetchall()]


def execute(sql: str, params=()) -> None:
    with _lock:
        conn = connect()
        conn.execute(sql, params)
        conn.commit()


ITEM_COLS = ["item_id", "type", "name", "series_id", "series_name", "season_number", "episode_number", "year",
             "genres", "studios", "people", "official_rating", "community_rating", "duration", "fetched_at"]
JSON_COLS = {"genres", "studios", "people", "transcode_reasons"}


def _value(col: str, v):
    return json.dumps(v, ensure_ascii=False) if col in JSON_COLS else v


def upsert_item(it: dict) -> None:
    updates = ", ".join(f"{c}=excluded.{c}" for c in ITEM_COLS[1:])
    execute(
        f"""INSERT INTO items ({",".join(ITEM_COLS)}) VALUES ({",".join("?" * len(ITEM_COLS))})
            ON CONFLICT(item_id) DO UPDATE SET {updates}""",
        [_value(c, it.get(c)) for c in ITEM_COLS],
    )


PLAY_COLS = ["item_id", "user_id", "user_name", "client", "device", "started_at", "ended_at", "watched", "duration",
             "progress", "counted", "completed", "play_method", "video_codec", "height", "audio_lang", "subtitle_lang",
             "transcode_reasons", "source"]


def insert_play(p: dict) -> None:
    execute(
        f"INSERT INTO plays ({','.join(PLAY_COLS)}) VALUES ({','.join('?' * len(PLAY_COLS))})",
        [_value(c, p.get(c, [] if c in JSON_COLS else None)) for c in PLAY_COLS],
    )
