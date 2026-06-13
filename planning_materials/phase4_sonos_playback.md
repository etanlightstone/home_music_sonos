# Phase 4: Sonos Playback & Controls Bar — Full Playback Integration

## What This Phase Builds
- `services/sonos_controller.py` — soco-based Sonos control (play URI, play folder queue, pause, resume, next, prev, state)
- `routers/sonos.py` — FastAPI endpoints for all Sonos playback operations
- Full playback controls bar (sticky, top of page) wired to both Sonos and in-browser audio
- In-browser playlist engine (HTML `<audio>` element + JS queue for folder playback)
- Wire all "▶ Browser" and "▶ Sonos" buttons from Phase 3

---

## Full App Context (Read Before Starting)
You are finalising **SonosWeb** — a dark-themed web app for browsing music on a remote SFTP/FTP server and playing it on Sonos speakers. Backend is Python FastAPI, frontend is vanilla HTML/CSS/JS.

**Already built (do not re-implement):**

| File | What it provides |
|------|-----------------|
| `database.py` | `get_db()` |
| `routers/settings.py` | `get_settings()` → dict with all config keys |
| `routers/proxy.py` | `build_proxy_url(rel_path, settings)` → full `http://` URL; `GET /api/proxy/{path}` streams file |
| `routers/files.py` | `GET /api/files/folder-files?path=` → `{ files: [{path, name, …}] }` |
| `static/style.css` | Full dark theme; all button/playbar CSS classes already defined |
| `templates/index.html` | `#playbar` (hidden), `#btn-prev`, `#btn-playpause`, `#btn-next`, `#now-playing-label`, `#now-playing-mode`, `#audio-player` (hidden `<audio>`), `.main-content` |
| `static/app.js` | Tab switching, settings, index polling, browser navigation, search. Phase 3 registered `.browser-play-btn`, `.sonos-play-btn`, `.sonos-folder-btn`, `.browser-folder-btn` click handlers that call `window.playInBrowser(path, name)`, `window.playOnSonos(path, name)`, `window.playFolderOnSonos(path, name)`, `window.playFolderInBrowser(path, name)` if they are defined |

**Key rule:** Phase 4 only needs to define `window.playInBrowser`, `window.playOnSonos`, `window.playFolderOnSonos`, and `window.playFolderInBrowser`. The Phase 3 click handlers will automatically start calling them.

**`entries.path`** is relative to `server_path` (e.g. `/Rock/song.mp3`). The proxy URL for Sonos is built via `build_proxy_url(rel_path, settings)` in `routers/proxy.py`.

---

## Files to Create / Modify

```
sonosweb/
├── services/
│   └── sonos_controller.py   ← CREATE
├── routers/
│   └── sonos.py              ← CREATE
├── static/
│   └── app.js                ← MODIFY (append playback engine)
└── main.py                   ← MODIFY (include sonos router)
```

---

## Implementation

### `services/sonos_controller.py`

Uses the `soco` library (already in `requirements.txt`). The `soco` library is synchronous; all calls that block should be wrapped in `run_in_executor` when called from async FastAPI endpoints.

```python
"""
Sonos controller using soco.
All public functions are synchronous — wrap in asyncio.run_in_executor
when calling from async FastAPI route handlers.
"""

import time
import json
from typing import Optional

try:
    import soco
    from soco.core import SoCo
    from soco.exceptions import SoCoException
except ImportError:
    raise ImportError("soco is not installed. Run: pip install soco")


def _player(ip: str) -> SoCo:
    return SoCo(ip)


# ── Single-file playback ─────────────────────────────────────

def play_uri(sonos_ip: str, uri: str, title: str = "") -> dict:
    """
    Play a single audio URI on the Sonos speaker.
    uri must be an http:// URL reachable from the Sonos device.
    """
    player = _player(sonos_ip)
    try:
        player.play_uri(uri)
        return {"status": "playing", "uri": uri, "title": title}
    except SoCoException as e:
        # Some Sonos devices need a stop before a new URI is accepted
        try:
            player.stop()
            time.sleep(0.3)
            player.play_uri(uri)
            return {"status": "playing", "uri": uri, "title": title}
        except Exception as e2:
            return {"status": "error", "message": str(e2)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Folder / queue playback ──────────────────────────────────

def play_queue(sonos_ip: str, uris: list[str], titles: list[str] = None) -> dict:
    """
    Clear the Sonos queue, load all URIs, and start playing from track 1.
    uris: list of http:// URLs in play order.
    titles: optional list of display titles (same length as uris).
    """
    if not uris:
        return {"status": "error", "message": "No URIs provided"}

    player = _player(sonos_ip)
    try:
        player.clear_queue()
        for i, uri in enumerate(uris):
            title = (titles[i] if titles and i < len(titles) else f"Track {i+1}")
            # add_uri_to_queue(uri) — soco auto-generates basic DIDL metadata
            player.add_uri_to_queue(uri)
        player.play_from_queue(0)
        return {
            "status": "playing_queue",
            "track_count": len(uris),
            "first_title": titles[0] if titles else uris[0].split('/')[-1],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Transport controls ───────────────────────────────────────

def pause(sonos_ip: str) -> dict:
    player = _player(sonos_ip)
    try:
        player.pause()
        return {"status": "paused"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def resume(sonos_ip: str) -> dict:
    player = _player(sonos_ip)
    try:
        player.play()
        return {"status": "playing"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def next_track(sonos_ip: str) -> dict:
    player = _player(sonos_ip)
    try:
        player.next()
        return {"status": "next"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def prev_track(sonos_ip: str) -> dict:
    player = _player(sonos_ip)
    try:
        player.previous()
        return {"status": "previous"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── State query ──────────────────────────────────────────────

def get_state(sonos_ip: str) -> dict:
    """
    Returns current transport state and track info.
    Useful for syncing the UI to what Sonos is actually playing.
    """
    player = _player(sonos_ip)
    try:
        transport = player.get_current_transport_info()
        track     = player.get_current_track_info()
        return {
            "state":    transport.get("current_transport_state", "UNKNOWN"),
            "title":    track.get("title", ""),
            "artist":   track.get("artist", ""),
            "album":    track.get("album", ""),
            "position": track.get("position", ""),
            "duration": track.get("duration", ""),
            "uri":      track.get("uri", ""),
        }
    except Exception as e:
        return {
            "state": "UNKNOWN",
            "title": "",
            "error": str(e),
        }
```

> **soco note on `add_uri_to_queue`:** If your Sonos device rejects URIs added to the queue without DIDL metadata, replace `player.add_uri_to_queue(uri)` with the DIDL version below. Most Sonos devices accept plain URIs for standard HTTP audio files, but some are stricter:
> ```python
> from soco.data_structures import DidlMusicTrack, DidlResource, to_didl_string
> res = DidlResource(uri=uri, protocol_info="http-get:*:audio/mpeg:*")
> item = DidlMusicTrack(title=title, parent_id='-1', item_id='-1', resources=[res])
> player.add_to_queue(item)
> ```

---

### `routers/sonos.py`

```python
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from routers.settings import get_settings
from routers.proxy import build_proxy_url
from services import sonos_controller as sc

router = APIRouter()


def _get_sonos_ip() -> str:
    return get_settings().get("sonos_ip", "10.0.1.90")


def _build_url(rel_path: str) -> str:
    """Build the proxy URL for a relative file path."""
    settings = get_settings()
    return build_proxy_url(rel_path, settings)


# ── Request models ───────────────────────────────────────────

class PlayFileRequest(BaseModel):
    path: str          # relative path, e.g. /Rock/song.mp3
    name: Optional[str] = ""


class PlayFolderRequest(BaseModel):
    path: str          # relative dir path, e.g. /Rock


# ── Endpoints ────────────────────────────────────────────────

@router.post("/play-file")
async def play_file(req: PlayFileRequest):
    """Play a single music file on Sonos."""
    sonos_ip = _get_sonos_ip()
    uri      = _build_url(req.path)
    title    = req.name or req.path.split('/')[-1]
    loop     = asyncio.get_event_loop()
    result   = await loop.run_in_executor(None, sc.play_uri, sonos_ip, uri, title)
    return {**result, "title": title, "proxy_url": uri}


@router.post("/play-folder")
async def play_folder(req: PlayFolderRequest):
    """
    Load all music files from a folder (recursive) into the Sonos queue
    and start playing from the first track.
    """
    from routers.files import folder_files  # reuse existing endpoint logic
    folder_data = folder_files(path=req.path)
    files = folder_data.get("files", [])

    if not files:
        return {"status": "error", "message": "No music files found in folder"}

    sonos_ip = _get_sonos_ip()
    uris     = [_build_url(f["path"]) for f in files]
    titles   = [f["name"] for f in files]

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, sc.play_queue, sonos_ip, uris, titles)
    return {
        **result,
        "folder": req.path,
        "track_count": len(files),
        "first_title": titles[0] if titles else "",
    }


@router.post("/pause")
async def pause():
    sonos_ip = _get_sonos_ip()
    loop     = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.pause, sonos_ip)


@router.post("/resume")
async def resume():
    sonos_ip = _get_sonos_ip()
    loop     = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.resume, sonos_ip)


@router.post("/next")
async def next_track():
    sonos_ip = _get_sonos_ip()
    loop     = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.next_track, sonos_ip)


@router.post("/previous")
async def previous_track():
    sonos_ip = _get_sonos_ip()
    loop     = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.prev_track, sonos_ip)


@router.get("/state")
async def sonos_state():
    sonos_ip = _get_sonos_ip()
    loop     = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.get_state, sonos_ip)
```

---

### Modify `main.py`

Add the Sonos router. Complete updated `main.py`:

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
from routers import files as files_router
from routers import sonos as sonos_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SonosWeb", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(index_router.router,    prefix="/api/index",    tags=["index"])
app.include_router(proxy.router,           prefix="/api/proxy",    tags=["proxy"])
app.include_router(files_router.router,    prefix="/api/files",    tags=["files"])
app.include_router(sonos_router.router,    prefix="/api/sonos",    tags=["sonos"])

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

---

### `static/app.js` — Phase 4 additions

Append all of the following to `app.js`. This block implements:
- The playback controls bar (show/hide, button handlers)
- In-browser audio engine with folder queue
- Sonos play functions exposed on `window.*`
- Sonos state polling (for controls bar sync)

```javascript
/* ============================================================
   PHASE 4 — Playback engine (Sonos + in-browser)
   ============================================================ */

// ── Shared playback state ────────────────────────────────────
const playback = {
    mode:          null,     // 'sonos' | 'browser' | null
    currentTitle:  '',
    isPlaying:     false,
    isPaused:      false,

    // In-browser playlist
    browserPlaylist: [],     // [{path, name, proxyUrl}]
    browserIndex:    -1,

    // Sonos polling
    sonosPoller: null,
};

// ── DOM refs ─────────────────────────────────────────────────
const audioEl       = document.getElementById('audio-player');
const playbar       = document.getElementById('playbar');
const btnPrev       = document.getElementById('btn-prev');
const btnPlayPause  = document.getElementById('btn-playpause');
const btnNext       = document.getElementById('btn-next');
const nowLabel      = document.getElementById('now-playing-label');
const nowMode       = document.getElementById('now-playing-mode');
const mainContent   = document.querySelector('.main-content');

// ── Initialise controls bar ──────────────────────────────────
document.addEventListener('DOMContentLoaded', initPlaybackControls);

function initPlaybackControls() {
    btnPrev?.addEventListener('click',      onPrev);
    btnPlayPause?.addEventListener('click', onPlayPause);
    btnNext?.addEventListener('click',      onNext);

    // In-browser audio events
    if (audioEl) {
        audioEl.addEventListener('ended',   onBrowserTrackEnded);
        audioEl.addEventListener('play',    () => setPlayPauseBtn(true));
        audioEl.addEventListener('pause',   () => setPlayPauseBtn(false));
        audioEl.addEventListener('error',   (e) => console.error('[Audio]', e));
    }
}

// ── Show/hide playbar ────────────────────────────────────────
function showPlaybar() {
    playbar?.classList.remove('hidden');
    mainContent?.classList.add('playbar-visible');
}

function updateNowPlaying(title, mode) {
    playback.currentTitle = title;
    playback.mode = mode;
    showPlaybar();
    if (nowLabel) nowLabel.textContent = title || 'Playing…';
    if (nowMode) {
        nowMode.textContent   = mode === 'sonos' ? 'Sonos' : 'Browser';
        nowMode.className     = `mode-badge ${mode}`;
    }
}

function setPlayPauseBtn(isPlaying) {
    playback.isPlaying = isPlaying;
    if (btnPlayPause) btnPlayPause.textContent = isPlaying ? '⏸' : '▶';
}

// ── Controls bar button handlers ────────────────────────────

function onPlayPause() {
    if (playback.mode === 'browser') {
        if (!audioEl) return;
        if (audioEl.paused) {
            audioEl.play();
        } else {
            audioEl.pause();
        }
    } else if (playback.mode === 'sonos') {
        if (playback.isPaused) {
            fetch('/api/sonos/resume', { method: 'POST' }).then(() => {
                playback.isPaused = false;
                setPlayPauseBtn(true);
            });
        } else {
            fetch('/api/sonos/pause', { method: 'POST' }).then(() => {
                playback.isPaused = true;
                setPlayPauseBtn(false);
            });
        }
    }
}

function onNext() {
    if (playback.mode === 'browser') {
        advanceBrowserPlaylist(1);
    } else if (playback.mode === 'sonos') {
        fetch('/api/sonos/next', { method: 'POST' })
            .then(r => r.json())
            .then(() => setTimeout(syncSonosState, 500));
    }
}

function onPrev() {
    if (playback.mode === 'browser') {
        advanceBrowserPlaylist(-1);
    } else if (playback.mode === 'sonos') {
        fetch('/api/sonos/previous', { method: 'POST' })
            .then(r => r.json())
            .then(() => setTimeout(syncSonosState, 500));
    }
}

// ── IN-BROWSER PLAYBACK ──────────────────────────────────────

/**
 * Play a single file in the browser.
 * Exposed on window so Phase 3's click handlers can call it.
 */
window.playInBrowser = function(relPath, name) {
    const proxyUrl = proxyUrlFromPath(relPath);
    playback.browserPlaylist = [{ path: relPath, name, proxyUrl }];
    playback.browserIndex    = 0;
    _startBrowserTrack(0);
};

/**
 * Load all files in a folder and play them in order in the browser.
 * Exposed on window.
 */
window.playFolderInBrowser = async function(folderPath, folderName) {
    try {
        const res  = await fetch(`/api/files/folder-files?path=${encodeURIComponent(folderPath)}`);
        const data = await res.json();
        const files = data.files || [];
        if (!files.length) { showToast('No music files found in folder', 'error'); return; }
        playback.browserPlaylist = files.map(f => ({
            path:     f.path,
            name:     f.name,
            proxyUrl: proxyUrlFromPath(f.path),
        }));
        playback.browserIndex = 0;
        _startBrowserTrack(0);
        showToast(`Playing ${files.length} tracks from "${folderName || folderPath}"`, 'success');
    } catch (err) {
        showToast('Failed to load folder: ' + err.message, 'error');
    }
};

function _startBrowserTrack(index) {
    if (!audioEl) return;
    const track = playback.browserPlaylist[index];
    if (!track) return;
    playback.browserIndex = index;
    audioEl.src = track.proxyUrl;
    audioEl.play().catch(err => console.error('[Audio] play error:', err));
    updateNowPlaying(track.name, 'browser');
    stopSonosPoller();
}

function onBrowserTrackEnded() {
    const nextIdx = playback.browserIndex + 1;
    if (nextIdx < playback.browserPlaylist.length) {
        _startBrowserTrack(nextIdx);
    } else {
        // Playlist finished
        setPlayPauseBtn(false);
        if (nowLabel) nowLabel.textContent = 'Playback finished';
    }
}

function advanceBrowserPlaylist(delta) {
    const nextIdx = playback.browserIndex + delta;
    if (nextIdx >= 0 && nextIdx < playback.browserPlaylist.length) {
        _startBrowserTrack(nextIdx);
    }
}

// ── SONOS PLAYBACK ───────────────────────────────────────────

/**
 * Play a single file on Sonos.
 * Exposed on window.
 */
window.playOnSonos = async function(relPath, name) {
    try {
        const res  = await fetch('/api/sonos/play-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: relPath, name }),
        });
        const data = await res.json();
        if (data.status === 'error') {
            showToast('Sonos error: ' + data.message, 'error');
            return;
        }
        // Stop any in-browser audio
        if (audioEl) { audioEl.pause(); audioEl.src = ''; }
        playback.isPaused = false;
        updateNowPlaying(name || relPath.split('/').pop(), 'sonos');
        setPlayPauseBtn(true);
        startSonosPoller();
        showToast(`Playing on Sonos: ${name}`, 'success');
    } catch (err) {
        showToast('Sonos play failed: ' + err.message, 'error');
    }
};

/**
 * Play all files in a folder on Sonos (queued in order).
 * Exposed on window.
 */
window.playFolderOnSonos = async function(folderPath, folderName) {
    showToast(`Loading "${folderName || folderPath}" into Sonos queue…`, 'success');
    try {
        const res  = await fetch('/api/sonos/play-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: folderPath }),
        });
        const data = await res.json();
        if (data.status === 'error') {
            showToast('Sonos error: ' + data.message, 'error');
            return;
        }
        // Stop any in-browser audio
        if (audioEl) { audioEl.pause(); audioEl.src = ''; }
        playback.isPaused = false;
        const firstTitle = data.first_title || folderName;
        updateNowPlaying(firstTitle, 'sonos');
        setPlayPauseBtn(true);
        startSonosPoller();
        showToast(`${data.track_count} tracks queued on Sonos`, 'success');
    } catch (err) {
        showToast('Sonos folder play failed: ' + err.message, 'error');
    }
};

// ── Sonos state polling ──────────────────────────────────────
// Poll Sonos every 3s while it's the active mode, to keep
// the "Now Playing" label and pause/play icon in sync.

function startSonosPoller() {
    stopSonosPoller();
    playback.sonosPoller = setInterval(syncSonosState, 3000);
}

function stopSonosPoller() {
    if (playback.sonosPoller) {
        clearInterval(playback.sonosPoller);
        playback.sonosPoller = null;
    }
}

async function syncSonosState() {
    if (playback.mode !== 'sonos') { stopSonosPoller(); return; }
    try {
        const res  = await fetch('/api/sonos/state');
        const data = await res.json();
        const state    = data.state || 'UNKNOWN';
        const title    = data.title || playback.currentTitle;
        const isPlaying = state === 'PLAYING';
        const isStopped = state === 'STOPPED' || state === 'NO_MEDIA_PRESENT';

        if (title && title !== playback.currentTitle) {
            updateNowPlaying(title, 'sonos');
        }
        playback.isPaused = (state === 'PAUSED_PLAYBACK');
        setPlayPauseBtn(isPlaying);

        // Stop polling if Sonos stopped
        if (isStopped) stopSonosPoller();
    } catch (err) {
        // Network error — keep polling, Sonos may be momentarily busy
    }
}

// ── Helper: build proxy URL from relative file path ──────────
// Mirrors the logic in routers/proxy.py:build_proxy_url,
// but done client-side so we don't need an extra API round-trip.
// This must match exactly: /api/proxy/ + path-without-leading-slash
function proxyUrlFromPath(relPath) {
    const clean = relPath.replace(/^\/+/, '');
    // Use relative URL so it works regardless of host/port
    return `/api/proxy/${clean}`;
}
```

---

## API Endpoints (Phase 4)

| Method | Path | Body / Params | Description |
|--------|------|---------------|-------------|
| `POST` | `/api/sonos/play-file` | `{path, name}` | Play one file on Sonos |
| `POST` | `/api/sonos/play-folder` | `{path}` | Queue whole folder, play from track 1 |
| `POST` | `/api/sonos/pause` | — | Pause Sonos |
| `POST` | `/api/sonos/resume` | — | Resume Sonos |
| `POST` | `/api/sonos/next` | — | Skip to next track (queue mode) |
| `POST` | `/api/sonos/previous` | — | Go to previous track (queue mode) |
| `GET`  | `/api/sonos/state` | — | Current transport state + track info |

### Example responses

**`POST /api/sonos/play-file`**
```json
{"status": "playing", "uri": "http://192.168.1.5:8000/api/proxy/Rock/song.mp3", "title": "song.mp3"}
```

**`GET /api/sonos/state`**
```json
{
  "state":    "PLAYING",
  "title":    "Thunderstruck",
  "artist":   "AC/DC",
  "album":    "The Razor's Edge",
  "position": "0:01:23",
  "duration": "0:04:51",
  "uri":      "http://192.168.1.5:8000/api/proxy/Rock/Thunderstruck.mp3"
}
```

---

## Validation Steps

### 1. Basic server startup
```bash
./app.sh
# No import errors. FastAPI docs at http://localhost:8000/docs
# Should list /api/sonos/* endpoints.
```

### 2. Test Sonos play-file via API directly
```bash
# First: find a file path from your index
sqlite3 sonosweb.db "SELECT path FROM entries WHERE is_directory=0 LIMIT 1;"
# e.g. /Rock/Thunderstruck.mp3

curl -X POST http://localhost:8000/api/sonos/play-file \
  -H "Content-Type: application/json" \
  -d '{"path": "/Rock/Thunderstruck.mp3", "name": "Thunderstruck.mp3"}'
# → {"status": "playing", ...}
# Sonos should start playing the file
```

### 3. Test Sonos state
```bash
curl http://localhost:8000/api/sonos/state
# → {"state": "PLAYING", "title": "Thunderstruck", ...}
```

### 4. Test pause / resume / next / prev
```bash
curl -X POST http://localhost:8000/api/sonos/pause
# → {"status": "paused"}

curl -X POST http://localhost:8000/api/sonos/resume
# → {"status": "playing"}
```

### 5. Test folder queue
```bash
# Find a folder path
sqlite3 sonosweb.db "SELECT path FROM entries WHERE is_directory=1 LIMIT 1;"

curl -X POST http://localhost:8000/api/sonos/play-folder \
  -H "Content-Type: application/json" \
  -d '{"path": "/Rock"}'
# → {"status": "playing_queue", "track_count": 12, ...}
# Sonos should start playing all files in /Rock in order
```

### 6. In-browser playback
- Open `http://localhost:8000` in browser.
- Navigate to any music file.
- Click "▶ Browser" — the playbar should appear at the top showing track name and "Browser" badge.
- The `<audio>` element should start playing (you should hear audio).
- Pause/resume with the ⏸/▶ button in the bar.

### 7. In-browser folder playback
- Click "▶ Browser" on a folder.
- Toast shows "Playing N tracks from …".
- Track auto-advances when each song ends.
- ⏮ / ⏭ buttons step through the playlist.

### 8. Sonos playback via UI
- Click "▶ Sonos" on a file.
- Toast shows "Playing on Sonos: …".
- Playbar shows track name with green "Sonos" badge.
- ⏸ pauses Sonos; ▶ resumes.
- Every 3 seconds the controls bar updates from `/api/sonos/state` (track title updates on Sonos side, e.g. when Sonos advances in queue).

### 9. Switching modes
- Play something in browser, then click "▶ Sonos" on another file.
- Browser audio stops, Sonos starts.
- (And vice versa — click "▶ Browser" while Sonos is playing: Sonos is NOT stopped automatically, only the UI mode switches. If you want to add auto-stop of Sonos when switching to browser, add `fetch('/api/sonos/pause', {method:'POST'})` in `window.playInBrowser`.)

---

## Notes & Gotchas

### Sonos requires a reachable HTTP URL
The file URLs sent to Sonos (e.g. `http://192.168.1.5:8000/api/proxy/Rock/song.mp3`) **must be reachable by the Sonos device**. If Sonos can't reach the URL, it will silently fail or show a cryptic error.
- Confirm `webserver_host` is set to your machine's LAN IP (or leave blank for auto-detect).
- Test reachability: `curl http://192.168.1.5:8000/api/proxy/Rock/song.mp3 --output /tmp/test.mp3` from another machine on the LAN.
- The app.sh script binds to `0.0.0.0`, so LAN access should work unless a firewall blocks port 8000.

### soco blocking calls
All `soco` functions are synchronous and can block for up to a second while sending UPnP commands. We wrap them in `asyncio.run_in_executor(None, ...)` so FastAPI's event loop is never blocked. Do not call soco functions directly in `async def` route handlers without this wrapper.

### Sonos `play_from_queue(0)` indexing
soco's `play_from_queue(index)` is **0-indexed**. Track 0 is the first track. This is different from the Sonos app's 1-indexed display.

### `add_uri_to_queue` vs `add_to_queue`
If `player.add_uri_to_queue(uri)` raises an exception (e.g. `SoCoUPnPException: UPnP Error 701`), your Sonos model requires proper DIDL-Lite metadata. Use the alternative shown in the soco note in `sonos_controller.py`. You'll need to set `protocol_info` correctly for each file type (e.g. `audio/flac` for FLAC). Easiest approach: detect the extension and set the right MIME type.

### Content-Length and Sonos seeking
For Sonos to display a progress bar and allow seeking, the proxy must return a `Content-Length` header. This is already handled in Phase 2's `routers/proxy.py` (it calls `get_file_size()` first). If SFTP connection overhead makes this too slow, you can disable it and Sonos will still play the file — just without a progress bar.

### Proxy URL in JS vs Python
`proxyUrlFromPath()` in JS builds a **relative URL** (`/api/proxy/Rock/song.mp3`). This works for in-browser playback since the browser resolves relative URLs against the current host. However, the URLs sent to Sonos via `/api/sonos/play-file` are built server-side using `build_proxy_url()` in `routers/proxy.py`, which generates full absolute URLs (`http://192.168.1.5:8000/api/proxy/...`). The JS proxy URL is only used for the browser `<audio>` element.

### Sonos state polling cadence
Polling every 3 seconds is a good balance — frequent enough to notice track changes, infrequent enough not to stress the Sonos device or the event loop. If the Sonos is on WiFi it may occasionally time out; the `try/except` in `syncSonosState` absorbs this silently.

### Stopping Sonos when switching to browser
The current implementation does not send a stop/pause to Sonos when the user clicks "▶ Browser". Both Sonos and the browser could technically be playing simultaneously. If this is undesirable, add to `window.playInBrowser`:
```javascript
window.playInBrowser = async function(relPath, name) {
    // Optionally pause Sonos first:
    if (playback.mode === 'sonos') {
        await fetch('/api/sonos/pause', { method: 'POST' });
    }
    stopSonosPoller();
    // ... rest of the function
};
```

### `soco` discovery vs direct IP
`services/sonos_controller.py` uses `SoCo(ip)` directly rather than `soco.discover()`. This is intentional — discovery uses multicast which may not work on all networks and is slow. The user configures the IP in Settings. If the user doesn't know their Sonos IP, they can run `python3 -c "import soco; print(soco.discover())"` from the command line.
