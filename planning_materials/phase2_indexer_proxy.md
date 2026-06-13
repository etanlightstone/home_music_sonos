# Phase 2: Indexer & File Proxy — SFTP/FTP Clients, Background Indexing, HTTP Proxy

## What This Phase Builds
- `services/sftp_client.py` — SFTP client wrapper using paramiko
- `services/ftp_client.py` — FTP client wrapper using ftplib
- `services/indexer.py` — background async task that recursively walks the remote server and writes all music files/folders into the `entries` DB table
- `routers/index_router.py` — API endpoints for starting, polling, and interrupting the indexer
- `routers/proxy.py` — HTTP proxy endpoint that streams audio files from SFTP/FTP to the browser or Sonos
- Wire everything into `main.py`

---

## Full App Context (Read Before Starting)
You are building **SonosWeb** — a web app that lets users browse music on a remote SFTP/FTP server and play it on Sonos speakers. The FastAPI backend runs on Python. The frontend is dark-themed plain HTML/CSS/JS.

**Phase 1 already built:** project structure, SQLite DB with all tables (`settings`, `index_status`, `entries`), settings API, and the HTML shell. All of the following already exist and must not be modified unless noted:
- `database.py` — provides `get_db()` and `init_db()`
- `routers/settings.py` — provides `get_settings()` returning a dict of config keys
- `main.py` — FastAPI app with lifespan, static files, templates mounted
- `sonosweb.db` — SQLite file with all tables created

**Phase 2 goal:** make the server index a remote SFTP/FTP music library into the DB, and serve those files over HTTP so Sonos can play them.

---

## Files to Create / Modify

```
sonosweb/
├── services/
│   ├── __init__.py            (exists, empty — leave it)
│   ├── sftp_client.py         ← CREATE
│   ├── ftp_client.py          ← CREATE
│   └── indexer.py             ← CREATE
├── routers/
│   ├── index_router.py        ← CREATE
│   └── proxy.py               ← CREATE
└── main.py                    ← MODIFY (add new routers)
```

---

## Key Design Decisions

### Path Convention in the `entries` Table
The `path` column in `entries` stores paths **relative to `server_path`** (the configured root on the remote server).

Example:
- `server_path` setting = `/home/music`
- Actual file on SFTP: `/home/music/Rock/AC DC - Thunderstruck.mp3`
- `entries.path` = `/Rock/AC DC - Thunderstruck.mp3`
- `entries.parent_path` = `/Rock`
- Root-level items have `parent_path = /`

The **proxy URL** is built from the relative path:
```
http://{webserver_host}/api/proxy/Rock/AC%20DC%20-%20Thunderstruck.mp3
```

The proxy receives `Rock/AC DC - Thunderstruck.mp3`, prepends `server_path`, and reads from SFTP/FTP.

### Supported Audio Extensions
Only index files with these extensions (case-insensitive):
```python
MUSIC_EXTENSIONS = {'mp3', 'wav', 'flac', 'aac', 'ogg', 'aiff', 'aif', 'm4a'}
```

### Background Task Approach
Use `asyncio.create_task()` — the indexer runs as a coroutine in the event loop. SFTP/FTP I/O (which is blocking) is offloaded to a thread pool executor with `await loop.run_in_executor(None, ...)`. This way the event loop is never blocked and the web server stays responsive during indexing.

### Webserver Base URL (for building Sonos-playable URLs)
Sonos on the LAN cannot use `localhost`. The proxy URL must use the machine's LAN IP. Use `webserver_host` from settings, or auto-detect:

```python
import socket

def get_base_url(settings: dict) -> str:
    host = settings.get("webserver_host", "").strip()
    if not host:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            host = f"{ip}:8000"
        except Exception:
            host = "localhost:8000"
    return f"http://{host}"
```

---

## Implementation

### `services/sftp_client.py`

```python
import paramiko
import stat as stat_module
from datetime import datetime, timezone


MUSIC_EXTENSIONS = {'mp3', 'wav', 'flac', 'aac', 'ogg', 'aiff', 'aif', 'm4a'}


class SFTPClient:
    """Synchronous SFTP client wrapper. Use as a context manager."""

    def __init__(self, settings: dict):
        self.host     = settings['server_host']
        self.port     = int(settings.get('server_port') or 22)
        self.username = settings['server_user']
        self.password = settings['server_password']
        self._ssh  = None
        self._sftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    def connect(self):
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=15,
            banner_timeout=30,
        )
        self._sftp = self._ssh.open_sftp()

    def close(self):
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._ssh:
                self._ssh.close()
        except Exception:
            pass

    def list_dir(self, path: str) -> list[dict]:
        """Return list of entries in `path`. Each entry is a dict with
        keys: name, is_dir, size, modified (ISO string or None)."""
        entries = []
        try:
            items = self._sftp.listdir_attr(path)
        except Exception as e:
            print(f"[SFTP] list_dir error for {path!r}: {e}")
            return entries

        for item in items:
            if item.filename.startswith('.'):
                continue  # skip hidden files
            is_dir = stat_module.S_ISDIR(item.st_mode) if item.st_mode else False
            modified = None
            if item.st_mtime:
                try:
                    modified = datetime.fromtimestamp(item.st_mtime, tz=timezone.utc).isoformat()
                except Exception:
                    pass
            entries.append({
                'name':    item.filename,
                'is_dir':  is_dir,
                'size':    item.st_size if not is_dir else None,
                'modified': modified,
            })
        return entries

    def read_file_chunks(self, path: str, chunk_size: int = 65536):
        """Generator yielding raw bytes chunks for streaming."""
        with self._sftp.open(path, 'rb') as f:
            f.prefetch()   # paramiko read-ahead for better throughput
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def get_file_size(self, path: str) -> int:
        return self._sftp.stat(path).st_size
```

---

### `services/ftp_client.py`

```python
import ftplib
import io
from datetime import datetime, timezone


class FTPClient:
    """Synchronous FTP client wrapper. Use as a context manager."""

    def __init__(self, settings: dict):
        self.host     = settings['server_host']
        self.port     = int(settings.get('server_port') or 21)
        self.username = settings['server_user']
        self.password = settings['server_password']
        self._ftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.close()

    def connect(self):
        self._ftp = ftplib.FTP()
        self._ftp.connect(self.host, self.port, timeout=15)
        self._ftp.login(self.username, self.password)
        self._ftp.set_pasv(True)

    def close(self):
        try:
            self._ftp.quit()
        except Exception:
            pass

    def list_dir(self, path: str) -> list[dict]:
        """Return list of entries. Uses MLSD if available, falls back to LIST."""
        entries = []
        try:
            # Try MLSD (modern, gives reliable metadata)
            for name, facts in self._ftp.mlsd(path):
                if name in ('.', '..') or name.startswith('.'):
                    continue
                is_dir = facts.get('type', '') == 'dir'
                size_str = facts.get('size', '')
                size = int(size_str) if size_str and not is_dir else None
                modified = None
                modify = facts.get('modify', '')
                if modify and len(modify) >= 14:
                    try:
                        modified = datetime(
                            int(modify[0:4]), int(modify[4:6]), int(modify[6:8]),
                            int(modify[8:10]), int(modify[10:12]), int(modify[12:14]),
                            tzinfo=timezone.utc
                        ).isoformat()
                    except Exception:
                        pass
                entries.append({'name': name, 'is_dir': is_dir, 'size': size, 'modified': modified})
        except ftplib.error_perm:
            # Fall back to LIST
            lines = []
            try:
                self._ftp.retrlines(f'LIST {path}', lines.append)
            except Exception as e:
                print(f"[FTP] list_dir error for {path!r}: {e}")
                return entries
            for line in lines:
                parts = line.split(None, 8)
                if len(parts) < 9:
                    continue
                name = parts[8].strip()
                if name in ('.', '..') or name.startswith('.'):
                    continue
                is_dir = line.startswith('d')
                size = None
                try:
                    if not is_dir:
                        size = int(parts[4])
                except (ValueError, IndexError):
                    pass
                entries.append({'name': name, 'is_dir': is_dir, 'size': size, 'modified': None})
        return entries

    def read_file_chunks(self, path: str, chunk_size: int = 65536):
        """Read entire file into memory then yield chunks.
        Note: FTP doesn't support true streaming easily in a generator context.
        For large files this will consume memory — acceptable for LAN use."""
        buf = io.BytesIO()
        self._ftp.retrbinary(f'RETR {path}', buf.write)
        buf.seek(0)
        while True:
            chunk = buf.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def get_file_size(self, path: str) -> int:
        return self._ftp.size(path)
```

---

### `services/indexer.py`

This is the most complex service. Key points:
- Module-level `_task` and `_cancel_flag` so only one indexing job runs at a time
- SFTP/FTP I/O runs in a thread pool executor (blocking calls off event loop)
- DB writes are batched per directory for efficiency
- `await asyncio.sleep(0)` yields control back to the event loop between directories

```python
import asyncio
from datetime import datetime, timezone
from database import get_db

MUSIC_EXTENSIONS = {'mp3', 'wav', 'flac', 'aac', 'ogg', 'aiff', 'aif', 'm4a'}

_task: asyncio.Task | None = None
_cancel_flag = asyncio.Event()   # set → stop indexing


def _get_settings():
    """Read settings synchronously from DB."""
    from routers.settings import get_settings
    return get_settings()


def _make_client(settings: dict):
    """Return the right client instance (not yet connected)."""
    if settings['server_type'] == 'sftp':
        from services.sftp_client import SFTPClient
        return SFTPClient(settings)
    else:
        from services.ftp_client import FTPClient
        return FTPClient(settings)


def is_music_file(name: str) -> bool:
    if '.' not in name:
        return False
    return name.rsplit('.', 1)[-1].lower() in MUSIC_EXTENSIONS


def _update_status(**kwargs):
    """Synchronous DB status update (called from executor or main thread)."""
    conn = get_db()
    sets = ', '.join(f"{k}=?" for k in kwargs)
    with conn:
        conn.execute(f"UPDATE index_status SET {sets} WHERE id=1", list(kwargs.values()))
    conn.close()


def get_status() -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM index_status WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {}


async def start_indexing() -> bool:
    """Start background indexing. Returns False if already running."""
    global _task, _cancel_flag
    if _task and not _task.done():
        return False
    _cancel_flag.clear()
    _task = asyncio.create_task(_run_indexing())
    return True


async def interrupt_indexing():
    """Cancel indexing and clear the entries table."""
    global _task, _cancel_flag
    _cancel_flag.set()
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM entries")
        conn.execute("""UPDATE index_status SET
            is_running=0, completed_at=NULL, was_interrupted=1,
            total_entries=0, processed_entries=0 WHERE id=1""")
    conn.close()


async def _run_indexing():
    """Main indexing coroutine."""
    settings = _get_settings()
    now = datetime.now(tz=timezone.utc).isoformat()

    conn = get_db()
    with conn:
        conn.execute("DELETE FROM entries")
        conn.execute("""UPDATE index_status SET
            is_running=1, started_at=?, completed_at=NULL,
            was_interrupted=0, total_entries=0, processed_entries=0
            WHERE id=1""", (now,))
    conn.close()

    loop = asyncio.get_event_loop()
    client = _make_client(settings)

    try:
        # Connect in thread pool (blocking)
        await loop.run_in_executor(None, client.connect)
        server_root = settings.get('server_path', '/').rstrip('/') or '/'
        await _index_dir(loop, client, server_root, server_root, '/')
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[Indexer] Fatal error: {e}")
    finally:
        try:
            await loop.run_in_executor(None, client.close)
        except Exception:
            pass
        _update_status(
            is_running=0,
            completed_at=datetime.now(tz=timezone.utc).isoformat()
        )


async def _index_dir(loop, client, server_root: str, abs_path: str, rel_path: str):
    """Recursively index one directory.
    - server_root: the configured server_path (e.g. /home/music)
    - abs_path:    absolute path on server (e.g. /home/music/Rock)
    - rel_path:    relative path stored in DB (e.g. /Rock)
    """
    if _cancel_flag.is_set():
        return

    # List directory in thread pool
    try:
        entries = await loop.run_in_executor(None, client.list_dir, abs_path)
    except Exception as e:
        print(f"[Indexer] list_dir failed for {abs_path!r}: {e}")
        return

    # Separate dirs and files
    dirs  = [e for e in entries if e['is_dir']]
    files = [e for e in entries if not e['is_dir'] and is_music_file(e['name'])]

    # Build batch for DB insert
    batch = []
    for d in dirs:
        child_rel = (rel_path.rstrip('/') + '/' + d['name']).replace('//', '/')
        batch.append((child_rel, d['name'], rel_path, 1, None, d.get('modified'), None))
    for f in files:
        child_rel = (rel_path.rstrip('/') + '/' + f['name']).replace('//', '/')
        ext = f['name'].rsplit('.', 1)[-1].lower()
        batch.append((child_rel, f['name'], rel_path, 0, f.get('size'), f.get('modified'), ext))

    if batch:
        conn = get_db()
        with conn:
            conn.executemany("""
                INSERT OR REPLACE INTO entries
                    (path, name, parent_path, is_directory, size, modified, extension)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, batch)
            conn.execute(
                "UPDATE index_status SET processed_entries = processed_entries + ? WHERE id=1",
                (len(batch),)
            )
        conn.close()

    # Yield to event loop
    await asyncio.sleep(0)

    # Recurse into subdirectories
    for d in dirs:
        if _cancel_flag.is_set():
            break
        child_abs = (abs_path.rstrip('/') + '/' + d['name']).replace('//', '/')
        child_rel = (rel_path.rstrip('/') + '/' + d['name']).replace('//', '/')
        await _index_dir(loop, client, server_root, child_abs, child_rel)
        await asyncio.sleep(0)
```

---

### `routers/index_router.py`

```python
from fastapi import APIRouter
from services import indexer

router = APIRouter()

@router.post("/start")
async def start_index():
    started = await indexer.start_indexing()
    if not started:
        return {"status": "already_running", "message": "Indexing is already in progress"}
    return {"status": "started"}

@router.get("/status")
def index_status():
    status = indexer.get_status()
    return {
        "is_running":         bool(status.get("is_running")),
        "started_at":         status.get("started_at"),
        "completed_at":       status.get("completed_at"),
        "processed_entries":  status.get("processed_entries", 0),
        "was_interrupted":    bool(status.get("was_interrupted")),
    }

@router.post("/interrupt")
async def interrupt_index():
    await indexer.interrupt_indexing()
    return {"status": "interrupted"}
```

---

### `routers/proxy.py`

Streams audio files from the remote SFTP/FTP server directly to the HTTP client. Sonos calls this URL to play the file.

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from urllib.parse import unquote
import socket

router = APIRouter()

CONTENT_TYPES = {
    'mp3':  'audio/mpeg',
    'wav':  'audio/wav',
    'flac': 'audio/flac',
    'aac':  'audio/aac',
    'ogg':  'audio/ogg',
    'm4a':  'audio/mp4',
    'aiff': 'audio/aiff',
    'aif':  'audio/aiff',
}


def get_base_url(settings: dict) -> str:
    """Build http://ip:port base URL for this server (LAN-accessible)."""
    host = settings.get("webserver_host", "").strip()
    if not host:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            host = f"{ip}:8000"
        except Exception:
            host = "localhost:8000"
    return f"http://{host}"


def build_proxy_url(rel_path: str, settings: dict) -> str:
    """Build the full proxy URL for a relative path (for Sonos to call)."""
    base = get_base_url(settings)
    safe_path = rel_path.lstrip('/')
    return f"{base}/api/proxy/{safe_path}"


def _make_client(settings: dict):
    if settings['server_type'] == 'sftp':
        from services.sftp_client import SFTPClient
        return SFTPClient(settings)
    else:
        from services.ftp_client import FTPClient
        return FTPClient(settings)


@router.get("/{file_path:path}")
async def proxy_audio(file_path: str):
    """
    Stream an audio file from the remote server.
    file_path is the relative path (matching entries.path without leading slash).
    The proxy prepends server_path from settings.
    """
    from routers.settings import get_settings
    settings = get_settings()

    if not settings.get('server_host'):
        raise HTTPException(status_code=503, detail="Server not configured")

    # Decode URL-encoded characters
    decoded_path = unquote(file_path)

    # Build absolute path on remote server
    server_root = settings.get('server_path', '/').rstrip('/')
    abs_path = f"{server_root}/{decoded_path.lstrip('/')}"

    # Determine content type
    ext = decoded_path.rsplit('.', 1)[-1].lower() if '.' in decoded_path else ''
    content_type = CONTENT_TYPES.get(ext, 'application/octet-stream')

    client = _make_client(settings)

    # Try to get file size for Content-Length (helps Sonos and browser scrubbing)
    headers = {}
    try:
        client.connect()
        size = client.get_file_size(abs_path)
        headers['Content-Length'] = str(size)
        headers['Accept-Ranges'] = 'bytes'
    except Exception:
        try:
            client.close()
        except Exception:
            pass
        client = _make_client(settings)
        try:
            client.connect()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"Cannot connect to server: {e}")

    def stream_generator():
        try:
            yield from client.read_file_chunks(abs_path)
        except Exception as e:
            print(f"[Proxy] Stream error for {abs_path!r}: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass

    return StreamingResponse(
        stream_generator(),
        media_type=content_type,
        headers=headers,
    )
```

> **Note:** The proxy opens a new SFTP/FTP connection for each file request. For a single-user local app this is fine. If connection setup latency is noticeable, a connection pool can be added later.

---

### Modify `main.py`

Add the two new routers. The complete `main.py` after modification:

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from contextlib import asynccontextmanager

from database import init_db
from routers import settings as settings_router
from routers import index_router
from routers import proxy

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SonosWeb", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(settings_router.router, prefix="/api/settings",  tags=["settings"])
app.include_router(index_router.router,    prefix="/api/index",      tags=["index"])
app.include_router(proxy.router,           prefix="/api/proxy",      tags=["proxy"])

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

---

### Wire up the Index UI in `static/app.js`

Add these functions to `app.js`. They handle the Re-index button, interrupt button, and index progress polling on both the Browser tab banner and the Settings tab.

```javascript
/* ── Index management ─────────────────────────────────────── */

let indexPollTimer = null;

async function startIndexing() {
    const res = await fetch('/api/index/start', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'started' || data.status === 'already_running') {
        startIndexPoll();
    } else {
        showToast('Failed to start indexing', 'error');
    }
}

async function interruptIndexing() {
    await fetch('/api/index/interrupt', { method: 'POST' });
    stopIndexPoll();
    updateIndexUI({ is_running: false, was_interrupted: true, processed_entries: 0, completed_at: null });
    showToast('Indexing interrupted', 'error');
}

function startIndexPoll() {
    if (indexPollTimer) clearInterval(indexPollTimer);
    pollIndexStatus();  // immediate
    indexPollTimer = setInterval(pollIndexStatus, 2000);
}

function stopIndexPoll() {
    if (indexPollTimer) { clearInterval(indexPollTimer); indexPollTimer = null; }
}

async function pollIndexStatus() {
    try {
        const res = await fetch('/api/index/status');
        const status = await res.json();
        updateIndexUI(status);
        if (!status.is_running) {
            stopIndexPoll();
            if (status.completed_at && window.loadBrowser) {
                loadBrowser('/');  // refresh browser (Phase 3 will define this)
            }
        }
    } catch (err) {
        console.error('Index poll error:', err);
        stopIndexPoll();
    }
}

function updateIndexUI(status) {
    const isRunning = status.is_running;
    const count     = status.processed_entries ?? 0;
    const lastTime  = status.completed_at
        ? new Date(status.completed_at).toLocaleString()
        : 'Never';

    // Browser tab banner
    document.getElementById('indexing-banner')?.classList.toggle('hidden', !isRunning);
    const bannerCount = document.getElementById('banner-count');
    if (bannerCount) bannerCount.textContent = count;

    // Settings tab progress
    document.getElementById('settings-index-progress')?.classList.toggle('hidden', !isRunning);
    const settingsCount = document.getElementById('settings-index-count');
    if (settingsCount) settingsCount.textContent = count;

    // Last indexed text
    const lastEl = document.getElementById('last-indexed');
    if (lastEl) lastEl.textContent = isRunning ? 'In progress…' : lastTime;

    // Interrupt buttons
    document.getElementById('banner-interrupt-btn')?.classList.toggle('hidden', !isRunning);
    document.getElementById('interrupt-settings-btn')?.classList.toggle('hidden', !isRunning);
    document.getElementById('reindex-btn')?.classList.toggle('hidden', isRunning);
}

// Attach event listeners on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
    // (merge with existing DOMContentLoaded if already present)
    document.getElementById('reindex-btn')?.addEventListener('click', startIndexing);
    document.getElementById('interrupt-settings-btn')?.addEventListener('click', interruptIndexing);
    document.getElementById('banner-interrupt-btn')?.addEventListener('click', interruptIndexing);

    // Check index status on load
    fetch('/api/index/status').then(r => r.json()).then(status => {
        updateIndexUI(status);
        if (status.is_running) startIndexPoll();
    }).catch(() => {});
});
```

> **Merge note:** The `DOMContentLoaded` handler must be merged with the existing one from Phase 1. Either combine into one handler or use multiple `addEventListener` calls — both approaches work.

---

## API Endpoints (Phase 2)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/index/start` | Start background indexing |
| `GET` | `/api/index/status` | Get indexing job status |
| `POST` | `/api/index/interrupt` | Cancel indexing + clear entries |
| `GET` | `/api/proxy/{file_path:path}` | Stream audio file from remote server |

---

## Validation Steps

You'll need an accessible SFTP or FTP server with some music files. Test from the command line and browser.

### 1. Check the server runs
```bash
./app.sh
```
No import errors. Visit `http://localhost:8000`.

### 2. Configure settings
```bash
curl -X POST http://localhost:8000/api/settings \
  -H "Content-Type: application/json" \
  -d '{
    "server_type": "sftp",
    "server_host": "192.168.1.10",
    "server_port": "22",
    "server_user": "myuser",
    "server_password": "mypassword",
    "server_path": "/home/music"
  }'
```

### 3. Start indexing and poll status
```bash
curl -X POST http://localhost:8000/api/index/start
# → {"status": "started"}

# Poll every 2 seconds
curl http://localhost:8000/api/index/status
# → {"is_running": true, "processed_entries": 47, ...}

# Wait for completion
curl http://localhost:8000/api/index/status
# → {"is_running": false, "completed_at": "2024-...", "processed_entries": 312, ...}
```

### 4. Verify entries in DB
```bash
sqlite3 sonosweb.db "SELECT COUNT(*) FROM entries;"
# → 312 (or whatever your library size is)

sqlite3 sonosweb.db "SELECT path, name, is_directory FROM entries LIMIT 10;"
sqlite3 sonosweb.db "SELECT path FROM entries WHERE is_directory=0 LIMIT 3;"
```

### 5. Test the proxy
Take a real file path from the DB output above (e.g. `/Rock/song.mp3`) and request it:
```bash
curl -v "http://localhost:8000/api/proxy/Rock/song.mp3" --output /tmp/test.mp3
# Should download. Check: file /tmp/test.mp3  → "MPEG audio file"

# Test with spaces (URL-encoded)
curl -v "http://localhost:8000/api/proxy/Rock/AC%20DC%20-%20Thunderstruck.mp3" --output /tmp/test2.mp3
```

### 6. Test interrupt
```bash
curl -X POST http://localhost:8000/api/index/start
sleep 2
curl -X POST http://localhost:8000/api/index/interrupt
sqlite3 sonosweb.db "SELECT COUNT(*) FROM entries;"  # → 0
curl http://localhost:8000/api/index/status          # → was_interrupted: true
```

### 7. Verify UI indicators
- Go to Settings tab, click "Re-index Now"
- Banner should appear on Browser tab and Settings tab with spinner and count
- Interrupt button should appear, Re-index button should disappear
- After completion, "Last indexed" should show a timestamp

---

## Notes & Gotchas

- **Paramiko host key policy:** `AutoAddPolicy()` auto-accepts unknown host keys. This is fine for a local LAN app. On a strict network, use `RejectPolicy` and pre-add the host key.
- **asyncio.Event vs threading.Event:** `_cancel_flag` is `asyncio.Event()`. If you need to check it from a synchronous context (inside `run_in_executor`), use a regular `threading.Event` alongside it. But for this design, the cancel check happens in the async coroutine so `asyncio.Event` is correct.
- **SFTP connection timeout:** Large libraries can take minutes to index. The paramiko SSH connection uses `timeout=15` for the initial connection only; the SFTP operations can take as long as needed.
- **FTP MLSD vs LIST:** MLSD is the modern standard. Most FTP servers support it. The fallback to LIST handles legacy servers. The LIST parsing is basic — if you see errors with a specific FTP server, the LIST format may differ. `ftplib.FTP_TLS` can be swapped in for FTPS servers.
- **The proxy creates a new connection per request** — this means an SFTP handshake for every audio file played. On LAN this is typically under 500ms. If it's too slow, a persistent connection pool (using a module-level connection) can be added.
- **Content-Length matters for Sonos** — Sonos needs `Content-Length` to know how long the file is. The proxy tries to get it with `get_file_size()` before streaming. If that fails, it streams without `Content-Length` (Sonos may not be able to seek/scrub).
- **Path handling:** When `server_path` is `/`, the root-level entries will have `parent_path = /` and `path = /songname.mp3`. Make sure path joining doesn't produce double slashes — the `.replace('//', '/')` calls in the indexer handle this.
- **Entries for directories:** Even if a directory contains no music files, it is still added to `entries` if traversed. This allows the browser to show the folder hierarchy correctly. Empty folders are an acceptable result.
- **`asyncio.sleep(0)` matters:** Without it, the indexer's recursive loop could starve the event loop on large libraries, causing API calls to time out during indexing. The `await asyncio.sleep(0)` after each directory yields control back.
