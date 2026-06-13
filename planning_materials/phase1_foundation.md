# Phase 1: Project Foundation — Scaffold, Database & Settings UI

## What This Phase Builds
The skeleton of the entire application: directory structure, FastAPI entry point, SQLite database (full schema defined upfront), settings CRUD API, a dark-themed HTML shell with two tabs (Browser | Settings), and the `app.sh` startup script. No music browsing or Sonos functionality yet — just a working server with persistable settings.

---

## Full App Context (Read Before Starting)
You are building **SonosWeb** — a web app that:
1. Reads music files from a remote **SFTP or FTP server** on the same LAN
2. Indexes them into a local **SQLite database** for fast browsing/search
3. Serves those files over HTTP as a **proxy** so a Sonos speaker can reach them
4. Controls a **Sonos speaker** via the `soco` Python library
5. Has a **dark-themed** plain HTML/CSS/vanilla JS frontend (no React/Vue)
6. Backend is **Python FastAPI**

This is Phase 1 of 4. Later phases add the indexer, file browser UI, and Sonos control.

---

## Project Structure to Create

```
sonosweb/
├── app.sh                    ← startup script (create this)
├── requirements.txt
├── main.py                   ← FastAPI app
├── database.py               ← SQLite init + connection helper
├── routers/
│   ├── __init__.py
│   └── settings.py           ← settings CRUD endpoints
├── services/
│   └── __init__.py           ← empty placeholder
├── static/
│   ├── style.css             ← dark theme
│   └── app.js                ← tab switching + settings form JS
└── templates/
    └── index.html            ← full HTML shell
```

---

## Database Schema

Define **ALL** tables now with `CREATE TABLE IF NOT EXISTS` so future phases never need schema migrations.

### `settings` — key/value config store
```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
```

### `index_status` — singleton row tracking background indexing job
```sql
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
```

### `entries` — indexed music files and folders from the remote server
```sql
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
```

**Notes on `entries`:**
- `path` is the file/folder's path **relative to the configured `server_path`**. Example: if `server_path = /home/music` and the file is `/home/music/Rock/song.mp3`, then `path = /Rock/song.mp3`.
- `parent_path` is the parent directory's relative path, e.g. `/Rock`.
- The root level has `parent_path = /`.
- `extension` is lowercase without the dot, e.g. `mp3`, `flac`. `NULL` for directories.

---

## Settings Keys Reference

Use these **exact key names** everywhere in the project:

| Key | Default | Description |
|-----|---------|-------------|
| `sonos_ip` | `10.0.1.90` | Sonos speaker LAN IP |
| `server_type` | `sftp` | `sftp` or `ftp` |
| `server_host` | `` | SFTP/FTP server hostname or IP |
| `server_port` | `22` | Server port (22 for SFTP, 21 for FTP) |
| `server_user` | `` | Login username |
| `server_password` | `` | Login password |
| `server_path` | `/` | Root path on the remote server to index from |
| `webserver_host` | `` | This machine's LAN IP:port (e.g. `192.168.1.5:8000`). Used to build URLs for Sonos. Leave blank to auto-detect. |

---

## Implementation

### `requirements.txt`
```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
jinja2>=3.1.0
python-multipart>=0.0.9
aiofiles>=23.2.1
soco>=0.30.0
paramiko>=3.4.0
mutagen>=1.47.0
```

### `app.sh`
```bash
#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "Installing/updating dependencies..."
pip install -r requirements.txt -q

echo ""
echo "Starting SonosWeb at http://0.0.0.0:8000"
echo "Access from LAN at http://$(hostname -I | awk '{print $1}'):8000"
echo ""
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Run `chmod +x app.sh` after creating this file.

**Important:** `--host 0.0.0.0` is required (not `127.0.0.1`) so Sonos on the LAN can reach the file proxy.

---

### `database.py`
```python
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
```

---

### `main.py`
```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from contextlib import asynccontextmanager

from database import init_db
from routers import settings as settings_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SonosWeb", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

---

### `routers/__init__.py`
Empty file.

### `services/__init__.py`
Empty file.

---

### `routers/settings.py`
```python
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from database import get_db

router = APIRouter()

DEFAULTS = {
    "sonos_ip":       "10.0.1.90",
    "server_type":    "sftp",
    "server_host":    "",
    "server_port":    "22",
    "server_user":    "",
    "server_password": "",
    "server_path":    "/",
    "webserver_host": "",
}

class SettingsUpdate(BaseModel):
    sonos_ip:        Optional[str] = None
    server_type:     Optional[str] = None
    server_host:     Optional[str] = None
    server_port:     Optional[str] = None
    server_user:     Optional[str] = None
    server_password: Optional[str] = None
    server_path:     Optional[str] = None
    webserver_host:  Optional[str] = None

@router.get("")
def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    result = dict(DEFAULTS)
    for row in rows:
        result[row["key"]] = row["value"]
    return result

@router.post("")
def update_settings(data: SettingsUpdate):
    conn = get_db()
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    with conn:
        for key, value in updates.items():
            if key in DEFAULTS:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (key, value)
                )
    conn.close()
    return get_settings()
```

---

### `templates/index.html`

Full dark-themed HTML shell. Two tabs: **Browser** and **Settings**.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SonosWeb</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>

  <!-- Fixed top nav -->
  <nav class="topnav">
    <span class="app-title">🎵 SonosWeb</span>
    <div class="tab-links">
      <a href="#" class="tab-link active" data-tab="browser">Browser</a>
      <a href="#" class="tab-link" data-tab="settings">Settings</a>
    </div>
  </nav>

  <!-- Playback controls bar (hidden until playback starts) -->
  <div id="playbar" class="playbar hidden">
    <div class="playbar-controls">
      <button id="btn-prev" class="ctrl-btn" title="Previous">⏮</button>
      <button id="btn-playpause" class="ctrl-btn" title="Pause/Resume">⏸</button>
      <button id="btn-next" class="ctrl-btn" title="Next">⏭</button>
    </div>
    <div class="playbar-info">
      <span id="now-playing-label" class="now-playing-label">Nothing playing</span>
      <span id="now-playing-mode" class="mode-badge"></span>
    </div>
    <audio id="audio-player" hidden></audio>
  </div>

  <!-- Main content area -->
  <main class="main-content">

    <!-- BROWSER TAB -->
    <div id="tab-browser" class="tab-content active">

      <!-- Indexing in-progress banner (hidden by default) -->
      <div id="indexing-banner" class="indexing-banner hidden">
        <span class="spinner"></span>
        Indexing in progress: <strong id="banner-count">0</strong> entries found…
        <button id="banner-interrupt-btn" class="btn-danger btn-sm">Interrupt</button>
      </div>

      <!-- Search bar area (Phase 3 will populate this) -->
      <div id="search-bar-area" class="search-bar-area">
        <input type="text" id="search-input" class="search-input" placeholder="Search files and folders…" autocomplete="off">
        <div class="search-filters">
          <label><input type="radio" name="search-type" value="all" checked> All</label>
          <label><input type="radio" name="search-type" value="files"> Files</label>
          <label><input type="radio" name="search-type" value="folders"> Folders</label>
        </div>
      </div>

      <!-- File browser area (Phase 3 will populate this) -->
      <div id="browser-area">
        <div id="empty-state" class="empty-state">
          <p>📂 No music indexed yet.</p>
          <p>Go to <a href="#" class="tab-link" data-tab="settings">Settings</a> to configure your server and run the indexer.</p>
        </div>
        <div id="breadcrumb" class="breadcrumb hidden"></div>
        <div id="file-list" class="file-list hidden"></div>
      </div>
    </div>

    <!-- SETTINGS TAB -->
    <div id="tab-settings" class="tab-content hidden">
      <div class="settings-card">
        <h2>Sonos</h2>
        <form id="settings-form">
          <div class="form-group">
            <label for="sonos_ip">Speaker IP Address</label>
            <input type="text" id="sonos_ip" name="sonos_ip" placeholder="10.0.1.90">
          </div>

          <h2>Music Server</h2>
          <div class="form-group">
            <label for="server_type">Protocol</label>
            <select id="server_type" name="server_type">
              <option value="sftp">SFTP</option>
              <option value="ftp">FTP</option>
            </select>
          </div>
          <div class="form-group">
            <label for="server_host">Host / IP</label>
            <input type="text" id="server_host" name="server_host" placeholder="192.168.1.10">
          </div>
          <div class="form-group">
            <label for="server_port">Port</label>
            <input type="number" id="server_port" name="server_port" placeholder="22">
          </div>
          <div class="form-group">
            <label for="server_user">Username</label>
            <input type="text" id="server_user" name="server_user">
          </div>
          <div class="form-group">
            <label for="server_password">Password</label>
            <input type="password" id="server_password" name="server_password">
          </div>
          <div class="form-group">
            <label for="server_path">Root Path on Server</label>
            <input type="text" id="server_path" name="server_path" placeholder="/home/music">
          </div>

          <h2>Advanced</h2>
          <div class="form-group">
            <label for="webserver_host">
              This Server's LAN Address
              <span class="label-hint">(leave blank to auto-detect — used to build URLs for Sonos)</span>
            </label>
            <input type="text" id="webserver_host" name="webserver_host" placeholder="192.168.1.5:8000">
          </div>
        </form>

        <div class="form-actions">
          <button id="save-settings-btn" class="btn-primary">Save Settings</button>
        </div>
      </div>

      <div class="settings-card">
        <h2>Music Index</h2>
        <p class="index-meta">
          Last indexed: <span id="last-indexed">Never</span>
        </p>
        <div id="settings-index-progress" class="indexing-banner hidden">
          <span class="spinner"></span>
          Indexing… <strong id="settings-index-count">0</strong> entries found
        </div>
        <div class="form-actions">
          <button id="reindex-btn" class="btn-primary">Re-index Now</button>
          <button id="interrupt-settings-btn" class="btn-danger hidden">Interrupt & Clear</button>
        </div>
      </div>
    </div>

  </main>

  <!-- Toast notification container -->
  <div id="toast-container"></div>

  <script src="/static/app.js"></script>
</body>
</html>
```

---

### `static/style.css`

Complete dark theme. Include all of these sections:

```css
/* ============================================================
   CSS VARIABLES — dark theme
   ============================================================ */
:root {
  --bg-primary:    #111111;
  --bg-secondary:  #1a1a1a;
  --bg-tertiary:   #252525;
  --bg-hover:      #2e2e2e;
  --text-primary:  #e8e8e8;
  --text-secondary:#999999;
  --text-muted:    #666666;
  --accent:        #1db954;
  --accent-hover:  #19a349;
  --accent-dim:    rgba(29,185,84,0.15);
  --danger:        #e05252;
  --danger-hover:  #c73f3f;
  --border:        #2f2f2f;
  --border-hover:  #444444;
  --playbar-bg:    #0d0d0d;
  --font:          -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  --font-mono:     'SF Mono', 'Fira Code', Consolas, monospace;
  --radius:        6px;
  --radius-sm:     4px;
  --topnav-h:      52px;
  --playbar-h:     60px;
}

/* ============================================================
   RESET + BASE
   ============================================================ */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; }
body {
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: var(--font);
  min-height: 100vh;
  line-height: 1.5;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ============================================================
   TOP NAV
   ============================================================ */
.topnav {
  position: fixed;
  top: 0; left: 0; right: 0;
  height: var(--topnav-h);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 24px;
  z-index: 100;
}
.app-title {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.3px;
}
.tab-links { display: flex; gap: 4px; margin-left: auto; }
.tab-link {
  padding: 6px 16px;
  border-radius: var(--radius);
  color: var(--text-secondary);
  font-size: 0.9rem;
  font-weight: 500;
  transition: background 0.15s, color 0.15s;
}
.tab-link:hover { background: var(--bg-tertiary); color: var(--text-primary); text-decoration: none; }
.tab-link.active { background: var(--accent-dim); color: var(--accent); }

/* ============================================================
   PLAYBAR (fixed, below nav)
   ============================================================ */
.playbar {
  position: fixed;
  top: var(--topnav-h);
  left: 0; right: 0;
  height: var(--playbar-h);
  background: var(--playbar-bg);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 20px;
  z-index: 99;
}
.playbar.hidden { display: none; }
.playbar-controls { display: flex; gap: 8px; }
.ctrl-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-primary);
  border-radius: var(--radius);
  padding: 6px 12px;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.ctrl-btn:hover { background: var(--bg-tertiary); border-color: var(--border-hover); }
.playbar-info { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.now-playing-label {
  font-size: 0.9rem;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.mode-badge {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 20px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}
.mode-badge.sonos { background: var(--accent-dim); color: var(--accent); }
.mode-badge.browser { background: rgba(100,140,255,0.15); color: #6699ff; }

/* ============================================================
   MAIN CONTENT
   ============================================================ */
.main-content {
  padding-top: var(--topnav-h);  /* shifts down when playbar is hidden */
  max-width: 1100px;
  margin: 0 auto;
  padding-left: 20px;
  padding-right: 20px;
  padding-bottom: 40px;
}
.main-content.playbar-visible { padding-top: calc(var(--topnav-h) + var(--playbar-h)); }

.tab-content { padding-top: 20px; }
.tab-content.hidden { display: none; }

/* ============================================================
   INDEXING BANNER
   ============================================================ */
.indexing-banner {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 16px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.9rem;
  color: var(--text-secondary);
}
.indexing-banner.hidden { display: none; }
.spinner {
  width: 14px; height: 14px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ============================================================
   SEARCH BAR
   ============================================================ */
.search-bar-area {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.search-input {
  flex: 1;
  min-width: 200px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 14px;
  color: var(--text-primary);
  font-size: 0.95rem;
  outline: none;
  transition: border-color 0.15s;
}
.search-input:focus { border-color: var(--accent); }
.search-filters { display: flex; gap: 12px; align-items: center; flex-shrink: 0; }
.search-filters label {
  display: flex; align-items: center; gap: 5px;
  font-size: 0.85rem; color: var(--text-secondary);
  cursor: pointer;
}
.search-filters input[type="radio"] { accent-color: var(--accent); }

/* ============================================================
   BREADCRUMB
   ============================================================ */
.breadcrumb {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.breadcrumb.hidden { display: none; }
.breadcrumb a { color: var(--text-secondary); }
.breadcrumb a:hover { color: var(--text-primary); }
.breadcrumb .crumb-sep { color: var(--text-muted); }
.breadcrumb .crumb-current { color: var(--text-primary); }

/* ============================================================
   FILE LIST
   ============================================================ */
.file-list { border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.file-list.hidden { display: none; }

.file-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  transition: background 0.1s;
}
.file-row:last-child { border-bottom: none; }
.file-row:hover { background: var(--bg-hover); }

.file-icon {
  font-size: 1rem;
  flex-shrink: 0;
  width: 28px;
  text-align: center;
}
.ext-badge {
  font-size: 0.65rem;
  font-family: var(--font-mono);
  padding: 2px 5px;
  border-radius: 3px;
  font-weight: 700;
  text-transform: uppercase;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  letter-spacing: 0.3px;
}
.ext-mp3  { background: rgba(29,185,84,0.2);  color: #1db954; }
.ext-flac { background: rgba(255,200,50,0.2);  color: #ffc832; }
.ext-wav  { background: rgba(100,140,255,0.2); color: #6699ff; }
.ext-m4a, .ext-aac { background: rgba(255,100,100,0.2); color: #ff6464; }

.file-name {
  flex: 1;
  min-width: 0;
  font-size: 0.9rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.folder-row .file-name { font-weight: 500; cursor: pointer; }
.folder-row .file-name:hover { color: var(--accent); }

.file-meta {
  font-size: 0.78rem;
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.file-actions { display: flex; gap: 6px; flex-shrink: 0; }

/* ============================================================
   BUTTONS
   ============================================================ */
.btn-primary {
  background: var(--accent);
  color: #000;
  border: none;
  border-radius: var(--radius);
  padding: 6px 14px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
  white-space: nowrap;
}
.btn-primary:hover { background: var(--accent-hover); }

.btn-secondary {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 14px;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  white-space: nowrap;
}
.btn-secondary:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border-hover); }

.btn-danger {
  background: var(--danger);
  color: #fff;
  border: none;
  border-radius: var(--radius);
  padding: 6px 14px;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-danger:hover { background: var(--danger-hover); }
.btn-sm { padding: 4px 10px; font-size: 0.78rem; }
.hidden { display: none !important; }

/* ============================================================
   EMPTY STATE
   ============================================================ */
.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-secondary);
  line-height: 2.2;
  font-size: 1rem;
}

/* ============================================================
   SETTINGS
   ============================================================ */
.settings-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 24px;
  margin-bottom: 20px;
}
.settings-card h2 {
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text-muted);
  margin-bottom: 16px;
  margin-top: 24px;
}
.settings-card h2:first-child { margin-top: 0; }

.form-group {
  margin-bottom: 14px;
}
.form-group label {
  display: block;
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: 5px;
  font-weight: 500;
}
.label-hint {
  font-size: 0.78rem;
  color: var(--text-muted);
  font-weight: 400;
}
.form-group input[type="text"],
.form-group input[type="password"],
.form-group input[type="number"],
.form-group select {
  width: 100%;
  max-width: 400px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 0.9rem;
  outline: none;
  transition: border-color 0.15s;
}
.form-group input:focus,
.form-group select:focus { border-color: var(--accent); }
.form-group select option { background: var(--bg-tertiary); }

.form-actions { display: flex; gap: 10px; margin-top: 20px; align-items: center; }
.index-meta { font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 12px; }

/* ============================================================
   TOAST NOTIFICATIONS
   ============================================================ */
#toast-container {
  position: fixed;
  bottom: 24px;
  right: 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 999;
}
.toast {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 16px;
  font-size: 0.88rem;
  color: var(--text-primary);
  animation: fadeInUp 0.2s ease;
  max-width: 300px;
}
.toast.success { border-left: 3px solid var(--accent); }
.toast.error   { border-left: 3px solid var(--danger); }
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

---

### `static/app.js`

Phase 1 only: tab switching and settings form. Future phases will add more code to this file.

```javascript
/* ============================================================
   SonosWeb — app.js
   Phase 1: Tab switching + Settings CRUD
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    loadSettings();
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);

    // Auto-update port when server type changes
    document.getElementById('server_type').addEventListener('change', (e) => {
        const portInput = document.getElementById('server_port');
        if (portInput.value === '22' || portInput.value === '21' || portInput.value === '') {
            portInput.value = e.target.value === 'sftp' ? '22' : '21';
        }
    });
});

/* ── Tab switching ─────────────────────────────────────────── */
function initTabs() {
    document.querySelectorAll('.tab-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            switchTab(link.dataset.tab);
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.add('hidden'));
    document.querySelectorAll('.tab-link').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + tabId)?.classList.remove('hidden');
    document.querySelectorAll(`.tab-link[data-tab="${tabId}"]`).forEach(l => l.classList.add('active'));
}

/* ── Settings ──────────────────────────────────────────────── */
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        Object.entries(data).forEach(([key, value]) => {
            const el = document.querySelector(`[name="${key}"]`);
            if (el) el.value = value ?? '';
        });
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

async function saveSettings() {
    const form = document.getElementById('settings-form');
    const data = {};
    new FormData(form).forEach((v, k) => { data[k] = v; });
    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (res.ok) {
            showToast('Settings saved', 'success');
        } else {
            showToast('Save failed', 'error');
        }
    } catch (err) {
        showToast('Save failed: ' + err.message, 'error');
    }
}

/* ── Toast notifications ───────────────────────────────────── */
function showToast(msg, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
```

---

## API Endpoints (Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serve HTML shell |
| `GET` | `/api/settings` | Return all settings as JSON |
| `POST` | `/api/settings` | Update settings (partial OK, null fields ignored) |

---

## Validation Steps

1. `chmod +x app.sh && ./app.sh`
2. Open `http://localhost:8000` in browser — dark page with **Browser** and **Settings** tabs appears
3. Click **Settings** tab — form with all fields visible
4. Fill in `sonos_ip`, set `server_type` to SFTP, notice port auto-updates to 22
5. Click **Save Settings** — toast shows "Settings saved"
6. Refresh page — all values still filled in (confirmed retrieval from DB)
7. Verify via curl:
   ```bash
   curl http://localhost:8000/api/settings
   # → JSON with sonos_ip, server_type, etc.

   curl -X POST http://localhost:8000/api/settings \
     -H "Content-Type: application/json" \
     -d '{"sonos_ip":"10.0.1.99"}'
   # → updated JSON, sonos_ip is now 10.0.1.99
   ```
8. Confirm `sonosweb.db` file was created in the project folder

---

## Notes & Gotchas

- Use `PRAGMA journal_mode=WAL` — this allows the web server to read the DB while the indexer is writing to it (Phase 2), avoiding "database is locked" errors.
- The `server_password` HTML input must use `type="password"` — it's already in the template above.
- `--host 0.0.0.0` in `app.sh` is **required** — Sonos (on LAN) must be able to reach this server to download audio files via the proxy built in Phase 2.
- The playbar div exists in the HTML but is hidden. Phases 3/4 will show it when playback starts.
- The `main-content` div will need the class `playbar-visible` added by JS when the playbar is shown, to push content down correctly.
- Do not add `--reload` removal note; `--reload` is fine for this local-use app.
- All `db.close()` calls are important — `WAL` mode is great but unclosed connections can still cause issues during indexing.
