import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "sonosweb.db")

def get_db() -> sqlite3.Connection:
    """Open a DB connection with Row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # allows concurrent reads during indexing
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    """Create all tables. Safe to call repeatedly."""
    conn = get_db()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS index_status (
                id                  INTEGER PRIMARY KEY CHECK (id = 1),
                is_running          INTEGER DEFAULT 0,
                started_at          TEXT,
                completed_at        TEXT,
                total_entries       INTEGER DEFAULT 0,
                processed_entries   INTEGER DEFAULT 0,
                was_interrupted     INTEGER DEFAULT 0
            );
            INSERT OR IGNORE INTO index_status (id) VALUES (1);

            CREATE TABLE IF NOT EXISTS entries (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                path         TEXT UNIQUE NOT NULL,
                name         TEXT NOT NULL,
                parent_path  TEXT NOT NULL,
                is_directory INTEGER NOT NULL DEFAULT 0,
                size         INTEGER,
                modified     TEXT,
                extension    TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_entries_parent ON entries(parent_path);
            CREATE INDEX IF NOT EXISTS idx_entries_path   ON entries(path);
            CREATE INDEX IF NOT EXISTS idx_entries_name   ON entries(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_entries_isdir  ON entries(is_directory);

            CREATE TABLE IF NOT EXISTS spotify_tokens (
                id            INTEGER PRIMARY KEY CHECK (id = 1),
                access_token  TEXT,
                refresh_token TEXT,
                expires_at    REAL    -- Unix timestamp when access_token expires
            );
            INSERT OR IGNORE INTO spotify_tokens (id) VALUES (1);

            CREATE TABLE IF NOT EXISTS spotify_pins (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type     TEXT NOT NULL CHECK(item_type IN ('artist', 'album', 'track')),
                spotify_id    TEXT NOT NULL,
                name          TEXT NOT NULL,
                -- Artist context (populated for album and track types; NULL for artist type)
                artist_id     TEXT,
                artist_name   TEXT,
                -- Album context (populated for track type; also self-referential for album type)
                album_id      TEXT,
                album_name    TEXT,
                -- Track-specific fields
                track_number  INTEGER,
                disc_number   INTEGER DEFAULT 1,
                duration_ms   INTEGER,
                -- Thumbnail for display (album art for all types; artist image for artist type)
                image_url     TEXT,
                -- Timestamp
                pinned_at     TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(item_type, spotify_id)
            );
            CREATE INDEX IF NOT EXISTS idx_pins_type       ON spotify_pins(item_type);
            CREATE INDEX IF NOT EXISTS idx_pins_artist_id  ON spotify_pins(artist_id);
            CREATE INDEX IF NOT EXISTS idx_pins_album_id   ON spotify_pins(album_id);
        """)
    conn.close()
