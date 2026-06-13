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
        """)
    conn.close()
