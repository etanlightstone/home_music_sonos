# Phase Spotify 1: Spotify Backend Foundation — OAuth, API Service & DB Schema

## What This Phase Builds
- New DB tables: `spotify_tokens` and `spotify_pins`
- Spotify credentials added to the Settings UI (Client ID, Client Secret, Redirect URI)
- OAuth flow: `/spotify/login` → Spotify → `/spotify/callback` — stores tokens in DB
- Token auto-refresh dependency used by all Spotify API endpoints
- `services/spotify_client.py` — spotipy-backed service for all Spotify metadata + player control calls
- `routers/spotify.py` — FastAPI router for OAuth routes and all Spotify API endpoints
- "Spotify" nav tab added (shows auth prompt if not logged in, placeholder if logged in)
- Logout endpoint
- Validation: can authenticate, tokens persist, metadata endpoints return data

---

## Full App Context
You are extending **SonosWeb**, a dark-themed LAN music web app. Backend: Python FastAPI. Frontend: vanilla HTML/CSS/JS. SQLite DB via `database.py` (`get_db()`). Settings stored as key/value in the `settings` table via `routers/settings.py` (`get_settings()` → dict). The app already has: SFTP/FTP music indexer, file proxy, Sonos control via soco, mp3 browser UI, search UI, spectrum visualizer.

**This phase is backend-focused.** The Spotify tab UI is a placeholder (auth prompt or "coming in next phase" skeleton). The browsing UI and playback are built in Phases 2 and 3.

---

## Files to Create / Modify

```
sonosweb/
├── services/
│   └── spotify_client.py        ← CREATE
├── routers/
│   └── spotify.py               ← CREATE
├── database.py                  ← MODIFY (add new tables to init_db)
├── main.py                      ← MODIFY (mount spotify router)
├── templates/
│   └── index.html               ← MODIFY (add Spotify nav tab + tab content shell)
├── static/
│   ├── style.css                ← MODIFY (add Spotify tab styles)
│   └── app.js                   ← MODIFY (add Spotify tab init)
└── requirements.txt             ← MODIFY (add spotipy)
```

---

## Database Schema Additions

Add these tables to `init_db()` in `database.py` alongside the existing `CREATE TABLE IF NOT EXISTS` calls:

### `spotify_tokens` — singleton row, stores OAuth tokens
```sql
CREATE TABLE IF NOT EXISTS spotify_tokens (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    access_token  TEXT,
    refresh_token TEXT,
    expires_at    REAL    -- Unix timestamp when access_token expires
);
INSERT OR IGNORE INTO spotify_tokens (id) VALUES (1);
```

### `spotify_pins` — the user's pinned Spotify library
```sql
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
```

**Pin data model — how the hierarchy is built:**
- `item_type = 'artist'`: just the artist (no album/track info). `artist_id` is NULL; `spotify_id` IS the artist ID. Artist appears in the pinned artists list; their albums are fetched live from Spotify API when drilled into.
- `item_type = 'album'`: a full album pin. `artist_id` and `artist_name` point to the parent artist. When an album is pinned, all its tracks are simultaneously inserted as `item_type = 'track'` rows.
- `item_type = 'track'`: a single track. Has `artist_id`, `album_id`, `track_number` etc. The pinned browser derives the artist and album from these fields.

---

## New Settings Keys

Add to `DEFAULTS` dict in `routers/settings.py` and add matching form fields to `templates/index.html`:

| Key | Default | Description |
|-----|---------|-------------|
| `spotify_client_id` | `` | From Spotify Developer Dashboard |
| `spotify_client_secret` | `` | From Spotify Developer Dashboard |
| `spotify_redirect_uri` | `http://localhost:8000/spotify/callback` | Must match exactly in Spotify Dev Dashboard |

Update the `SettingsUpdate` Pydantic model and `DEFAULTS` dict accordingly.

---

## `requirements.txt` addition

```
spotipy>=2.23.0
```

---

## Implementation

### `services/spotify_client.py`

```python
"""
Spotify API service layer.
All methods are synchronous — call via asyncio.run_in_executor from async route handlers.
"""

import time
import requests
from base64 import b64encode
from typing import Optional

try:
    import spotipy
except ImportError:
    raise ImportError("spotipy not installed. Run: pip install spotipy")


# ── Scopes required by this app ───────────────────────────────
SPOTIFY_SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "streaming",               # Spotify Web Playback SDK (Phase 3, requires Premium)
    "playlist-read-private",
    "playlist-read-collaborative",
])


# ── Token management (DB ↔ Spotify accounts API) ─────────────

def get_stored_tokens() -> Optional[dict]:
    """Read tokens from DB. Returns None if never authenticated."""
    from database import get_db
    conn = get_db()
    row = conn.execute("SELECT * FROM spotify_tokens WHERE id=1").fetchone()
    conn.close()
    if not row or not row["access_token"]:
        return None
    return dict(row)


def save_tokens(access_token: str, refresh_token: str, expires_in: int):
    """Persist tokens to DB."""
    from database import get_db
    expires_at = time.time() + expires_in - 60  # 60s buffer
    conn = get_db()
    with conn:
        conn.execute("""
            UPDATE spotify_tokens SET
                access_token=?, refresh_token=?, expires_at=?
            WHERE id=1
        """, (access_token, refresh_token, expires_at))
    conn.close()


def clear_tokens():
    from database import get_db
    conn = get_db()
    with conn:
        conn.execute("""
            UPDATE spotify_tokens SET
                access_token=NULL, refresh_token=NULL, expires_at=NULL
            WHERE id=1
        """)
    conn.close()


def _refresh_access_token(refresh_token: str, settings: dict) -> Optional[str]:
    """Exchange refresh_token for a new access_token. Returns new access_token or None."""
    client_id     = settings.get("spotify_client_id", "")
    client_secret = settings.get("spotify_client_secret", "")
    if not client_id or not client_secret:
        return None

    credentials = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        return None

    data = resp.json()
    new_access  = data.get("access_token")
    new_refresh = data.get("refresh_token", refresh_token)  # Spotify may rotate it
    expires_in  = data.get("expires_in", 3600)
    if new_access:
        save_tokens(new_access, new_refresh, expires_in)
    return new_access


def get_valid_access_token() -> Optional[str]:
    """
    Return a valid (non-expired) access token, auto-refreshing if needed.
    Returns None if not authenticated or refresh fails.
    """
    from routers.settings import get_settings
    tokens = get_stored_tokens()
    if not tokens:
        return None

    if time.time() < (tokens["expires_at"] or 0):
        return tokens["access_token"]   # still valid

    # Expired — refresh
    return _refresh_access_token(tokens["refresh_token"], get_settings())


# ── Spotify client factory ────────────────────────────────────

def make_client() -> Optional[spotipy.Spotify]:
    """Return a spotipy.Spotify instance with a valid token, or None."""
    token = get_valid_access_token()
    if not token:
        return None
    return spotipy.Spotify(auth=token)


# ── Auth URL builder ─────────────────────────────────────────

def get_auth_url(settings: dict) -> str:
    """Build the Spotify authorization URL for the OAuth redirect."""
    from urllib.parse import urlencode
    params = {
        "client_id":     settings.get("spotify_client_id", ""),
        "response_type": "code",
        "redirect_uri":  settings.get("spotify_redirect_uri", "http://localhost:8000/spotify/callback"),
        "scope":         SPOTIFY_SCOPES,
        "show_dialog":   "false",
    }
    return "https://accounts.spotify.com/authorize?" + urlencode(params)


def exchange_code_for_tokens(code: str, settings: dict) -> bool:
    """Exchange auth code from callback for access + refresh tokens. Returns True on success."""
    client_id     = settings.get("spotify_client_id", "")
    client_secret = settings.get("spotify_client_secret", "")
    redirect_uri  = settings.get("spotify_redirect_uri", "http://localhost:8000/spotify/callback")

    credentials = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":   "authorization_code",
            "code":         code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"[Spotify] Token exchange failed: {resp.text}")
        return False

    data = resp.json()
    save_tokens(
        data["access_token"],
        data["refresh_token"],
        data.get("expires_in", 3600),
    )
    return True


# ── Metadata API calls ───────────────────────────────────────

def _normalize_image(images: list) -> Optional[str]:
    """Pick the smallest image URL from Spotify's image array."""
    if not images:
        return None
    # Spotify returns images largest-first; pick last (smallest) for thumbnails
    return images[-1].get("url") if images else None


def search_spotify(q: str, types: str = "artist,album,track", limit: int = 10) -> dict:
    sp = make_client()
    if not sp:
        return {}
    raw = sp.search(q, type=types, limit=limit)

    result = {}
    if "artists" in raw:
        result["artists"] = [
            {
                "id":        a["id"],
                "name":      a["name"],
                "image_url": _normalize_image(a.get("images", [])),
                "uri":       a["uri"],
            }
            for a in raw["artists"]["items"]
        ]
    if "albums" in raw:
        result["albums"] = [
            {
                "id":          a["id"],
                "name":        a["name"],
                "artist_id":   a["artists"][0]["id"]   if a["artists"] else None,
                "artist_name": a["artists"][0]["name"] if a["artists"] else None,
                "image_url":   _normalize_image(a.get("images", [])),
                "release_year": (a.get("release_date", "") or "")[:4],
                "uri":          a["uri"],
            }
            for a in raw["albums"]["items"]
        ]
    if "tracks" in raw:
        result["tracks"] = [
            {
                "id":          t["id"],
                "name":        t["name"],
                "uri":         t["uri"],
                "artist_id":   t["artists"][0]["id"]   if t["artists"] else None,
                "artist_name": t["artists"][0]["name"] if t["artists"] else None,
                "album_id":    t["album"]["id"],
                "album_name":  t["album"]["name"],
                "track_number": t.get("track_number"),
                "disc_number":  t.get("disc_number", 1),
                "duration_ms":  t.get("duration_ms"),
                "image_url":   _normalize_image(t["album"].get("images", [])),
            }
            for t in raw["tracks"]["items"]
        ]
    return result


def get_artist_albums(artist_id: str) -> list[dict]:
    sp = make_client()
    if not sp:
        return []
    raw = sp.artist_albums(artist_id, album_type="album,single", limit=50)
    seen = set()
    albums = []
    for a in (raw.get("items") or []):
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        albums.append({
            "id":           a["id"],
            "name":         a["name"],
            "artist_id":    artist_id,
            "artist_name":  a["artists"][0]["name"] if a["artists"] else "",
            "image_url":    _normalize_image(a.get("images", [])),
            "release_year": (a.get("release_date", "") or "")[:4],
            "uri":          a["uri"],
            "album_type":   a.get("album_type", "album"),
        })
    return sorted(albums, key=lambda x: x["release_year"] or "0000", reverse=True)


def get_album_tracks(album_id: str) -> list[dict]:
    sp = make_client()
    if not sp:
        return []
    # Also fetch album to get images (album_tracks doesn't include them)
    album = sp.album(album_id)
    image_url = _normalize_image((album.get("images") or []))
    artist_id   = album["artists"][0]["id"]   if album.get("artists") else None
    artist_name = album["artists"][0]["name"] if album.get("artists") else None

    raw = sp.album_tracks(album_id, limit=50)
    tracks = []
    for t in (raw.get("items") or []):
        tracks.append({
            "id":           t["id"],
            "name":         t["name"],
            "uri":          t["uri"],
            "artist_id":    artist_id,
            "artist_name":  artist_name,
            "album_id":     album_id,
            "album_name":   album["name"],
            "track_number": t.get("track_number"),
            "disc_number":  t.get("disc_number", 1),
            "duration_ms":  t.get("duration_ms"),
            "image_url":    image_url,
        })
    return sorted(tracks, key=lambda x: (x["disc_number"] or 1, x["track_number"] or 0))


def get_user_playlists() -> list[dict]:
    sp = make_client()
    if not sp:
        return []
    raw = sp.current_user_playlists(limit=50)
    return [
        {
            "id":          p["id"],
            "name":        p["name"],
            "description": p.get("description", ""),
            "track_count": p["tracks"]["total"],
            "image_url":   _normalize_image(p.get("images", [])),
            "uri":         p["uri"],
        }
        for p in (raw.get("items") or []) if p
    ]


def get_playlist_tracks(playlist_id: str, offset: int = 0) -> list[dict]:
    sp = make_client()
    if not sp:
        return []
    raw = sp.playlist_tracks(playlist_id, limit=50, offset=offset)
    tracks = []
    for item in (raw.get("items") or []):
        t = item.get("track")
        if not t or t.get("is_local"):
            continue
        tracks.append({
            "id":           t["id"],
            "name":         t["name"],
            "uri":          t["uri"],
            "artist_id":    t["artists"][0]["id"]   if t.get("artists") else None,
            "artist_name":  t["artists"][0]["name"] if t.get("artists") else None,
            "album_id":     t["album"]["id"]   if t.get("album") else None,
            "album_name":   t["album"]["name"] if t.get("album") else None,
            "track_number": t.get("track_number"),
            "disc_number":  t.get("disc_number", 1),
            "duration_ms":  t.get("duration_ms"),
            "image_url":    _normalize_image((t.get("album") or {}).get("images", [])),
        })
    return tracks


# ── Playback control API calls ───────────────────────────────

def get_playback_state() -> Optional[dict]:
    sp = make_client()
    if not sp:
        return None
    try:
        state = sp.current_playback()
        if not state:
            return {"is_playing": False, "title": "", "artist": ""}
        track = state.get("item") or {}
        return {
            "is_playing":  state.get("is_playing", False),
            "title":       track.get("name", ""),
            "artist":      ", ".join(a["name"] for a in track.get("artists", [])),
            "album":       (track.get("album") or {}).get("name", ""),
            "uri":         track.get("uri", ""),
            "progress_ms": state.get("progress_ms", 0),
            "duration_ms": track.get("duration_ms", 0),
            "device_id":   (state.get("device") or {}).get("id"),
        }
    except Exception as e:
        print(f"[Spotify] get_playback_state error: {e}")
        return None


def spotify_play_track(track_uri: str, device_id: str = None):
    sp = make_client()
    if not sp:
        return {"error": "not authenticated"}
    try:
        sp.start_playback(device_id=device_id, uris=[track_uri])
        return {"status": "playing", "uri": track_uri}
    except Exception as e:
        return {"error": str(e)}


def spotify_play_tracks(track_uris: list[str], device_id: str = None):
    sp = make_client()
    if not sp:
        return {"error": "not authenticated"}
    try:
        sp.start_playback(device_id=device_id, uris=track_uris)
        return {"status": "playing", "count": len(track_uris)}
    except Exception as e:
        return {"error": str(e)}


def spotify_pause(device_id: str = None):
    sp = make_client()
    if sp:
        try:
            sp.pause_playback(device_id=device_id)
        except Exception:
            pass


def spotify_resume(device_id: str = None):
    sp = make_client()
    if sp:
        try:
            sp.start_playback(device_id=device_id)
        except Exception:
            pass


def spotify_next(device_id: str = None):
    sp = make_client()
    if sp:
        try:
            sp.next_track(device_id=device_id)
        except Exception:
            pass


def spotify_previous(device_id: str = None):
    sp = make_client()
    if sp:
        try:
            sp.previous_track(device_id=device_id)
        except Exception:
            pass
```

---

### `routers/spotify.py`

```python
from fastapi import APIRouter, Request, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
import asyncio

from routers.settings import get_settings
from services import spotify_client as sc

router = APIRouter()


# ── Auth check helper ─────────────────────────────────────────

def _is_authenticated() -> bool:
    return sc.get_valid_access_token() is not None


# ── OAuth endpoints ──────────────────────────────────────────

@router.get("/login")
def spotify_login():
    """Redirect user to Spotify authorization page."""
    settings = get_settings()
    if not settings.get("spotify_client_id"):
        return {"error": "Spotify Client ID not configured. Go to Settings."}
    auth_url = sc.get_auth_url(settings)
    return RedirectResponse(url=auth_url)


@router.get("/callback")
def spotify_callback(code: Optional[str] = None, error: Optional[str] = None):
    """Spotify redirects here after user approves. Exchange code for tokens."""
    if error:
        return RedirectResponse(url="/?spotify_auth=error")
    if not code:
        return RedirectResponse(url="/?spotify_auth=error")

    settings = get_settings()
    success = sc.exchange_code_for_tokens(code, settings)
    if success:
        return RedirectResponse(url="/?spotify_auth=success&tab=spotify")
    return RedirectResponse(url="/?spotify_auth=error")


@router.post("/logout")
def spotify_logout():
    sc.clear_tokens()
    return {"status": "logged_out"}


@router.get("/auth-status")
def auth_status():
    return {"authenticated": _is_authenticated()}


@router.get("/token")
def get_token():
    """Return current valid access token (for Spotify Web Playback SDK in Phase 3)."""
    token = sc.get_valid_access_token()
    if not token:
        return {"error": "not authenticated"}, 401
    return {"access_token": token}


# ── Metadata endpoints ────────────────────────────────────────

@router.get("/search")
async def search(q: str = Query(...), types: str = Query(default="artist,album,track")):
    if not _is_authenticated():
        return {"error": "not authenticated"}
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, sc.search_spotify, q, types)
    return result


@router.get("/artist/{artist_id}/albums")
async def artist_albums(artist_id: str):
    if not _is_authenticated():
        return {"error": "not authenticated"}
    loop = asyncio.get_event_loop()
    albums = await loop.run_in_executor(None, sc.get_artist_albums, artist_id)
    return {"artist_id": artist_id, "albums": albums}


@router.get("/album/{album_id}/tracks")
async def album_tracks(album_id: str):
    if not _is_authenticated():
        return {"error": "not authenticated"}
    loop = asyncio.get_event_loop()
    tracks = await loop.run_in_executor(None, sc.get_album_tracks, album_id)
    return {"album_id": album_id, "tracks": tracks}


@router.get("/playlists")
async def user_playlists():
    if not _is_authenticated():
        return {"error": "not authenticated"}
    loop = asyncio.get_event_loop()
    playlists = await loop.run_in_executor(None, sc.get_user_playlists)
    return {"playlists": playlists}


@router.get("/playlist/{playlist_id}/tracks")
async def playlist_tracks(playlist_id: str, offset: int = Query(default=0)):
    if not _is_authenticated():
        return {"error": "not authenticated"}
    loop = asyncio.get_event_loop()
    tracks = await loop.run_in_executor(
        None, sc.get_playlist_tracks, playlist_id, offset
    )
    return {"playlist_id": playlist_id, "tracks": tracks, "offset": offset}


# ── Playback control ─────────────────────────────────────────

class PlayTrackRequest(BaseModel):
    uri: str              # spotify:track:xxx
    device_id: Optional[str] = None

class PlayTracksRequest(BaseModel):
    uris: list[str]       # list of spotify:track:xxx
    device_id: Optional[str] = None

@router.post("/player/play-track")
async def player_play_track(req: PlayTrackRequest):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.spotify_play_track, req.uri, req.device_id)

@router.post("/player/play-tracks")
async def player_play_tracks(req: PlayTracksRequest):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.spotify_play_tracks, req.uris, req.device_id)

@router.post("/player/pause")
async def player_pause():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sc.spotify_pause)
    return {"status": "paused"}

@router.post("/player/resume")
async def player_resume():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sc.spotify_resume)
    return {"status": "playing"}

@router.post("/player/next")
async def player_next():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sc.spotify_next)
    return {"status": "next"}

@router.post("/player/previous")
async def player_previous():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sc.spotify_previous)
    return {"status": "previous"}

@router.get("/player/state")
async def player_state():
    loop = asyncio.get_event_loop()
    state = await loop.run_in_executor(None, sc.get_playback_state)
    return state or {"is_playing": False, "title": "", "artist": ""}
```

---

### Modify `main.py` — add Spotify router

```python
from routers import spotify as spotify_router
# ... existing imports and mounts ...
app.include_router(spotify_router.router, prefix="/api/spotify", tags=["spotify"])
```

Also add the plain OAuth redirect routes at the top level (not under `/api/`):

```python
# OAuth routes at root level (Spotify redirects back here)
@app.get("/spotify/login")
async def spotify_login_redirect():
    from routers.spotify import spotify_login
    return spotify_login()

@app.get("/spotify/callback")
async def spotify_callback_handler(code: str = None, error: str = None):
    from routers.spotify import spotify_callback
    return spotify_callback(code=code, error=error)
```

---

### Modify `routers/settings.py` — add Spotify settings keys

In `DEFAULTS`:
```python
DEFAULTS = {
    # ... existing keys ...
    "spotify_client_id":     "",
    "spotify_client_secret": "",
    "spotify_redirect_uri":  "http://localhost:8000/spotify/callback",
}
```

Add matching fields to `SettingsUpdate`:
```python
class SettingsUpdate(BaseModel):
    # ... existing fields ...
    spotify_client_id:     Optional[str] = None
    spotify_client_secret: Optional[str] = None
    spotify_redirect_uri:  Optional[str] = None
```

---

### Modify `templates/index.html`

#### 1. Add "Spotify" tab link to navbar

```html
<div class="tab-links">
  <a href="#" class="tab-link active" data-tab="browser">Browser</a>
  <a href="#" class="tab-link" data-tab="spotify">Spotify</a>  <!-- ADD -->
  <a href="#" class="tab-link" data-tab="settings">Settings</a>
</div>
```

#### 2. Add Spotify tab content shell (between browser and settings tab divs)

```html
<!-- SPOTIFY TAB -->
<div id="tab-spotify" class="tab-content hidden">

  <!-- Auth prompt — shown when not logged in -->
  <div id="spotify-auth-prompt" class="spotify-auth-prompt hidden">
    <div class="spotify-auth-card">
      <span class="spotify-logo">🎵</span>
      <h2>Connect Spotify</h2>
      <p>Log in with Spotify to browse your pinned library and play music on Sonos.</p>
      <p class="auth-hint">
        You need a <a href="https://developer.spotify.com/dashboard" target="_blank">Spotify Developer App</a>
        with redirect URI set to <code id="redirect-uri-display">http://localhost:8000/spotify/callback</code>.<br>
        Add your Client ID and Secret in <a href="#" class="tab-link" data-tab="settings">Settings</a> first.
      </p>
      <a href="/spotify/login" class="btn-spotify-login">Login with Spotify</a>
    </div>
  </div>

  <!-- Main Spotify browser — shown when authenticated (Phase 2 populates this) -->
  <div id="spotify-browser" class="hidden">
    <!-- Phases 2 & 3 build this out -->
    <p style="color: var(--text-muted); padding: 40px; text-align: center;">
      Spotify browser coming in Phase 2.
    </p>
  </div>

</div>
```

#### 3. Add Spotify section to Settings form

Inside `#settings-form`, after the existing Advanced section:

```html
<h2>Spotify</h2>
<div class="form-group">
  <label for="spotify_client_id">Client ID</label>
  <input type="text" id="spotify_client_id" name="spotify_client_id" placeholder="From developer.spotify.com/dashboard">
</div>
<div class="form-group">
  <label for="spotify_client_secret">Client Secret</label>
  <input type="password" id="spotify_client_secret" name="spotify_client_secret">
</div>
<div class="form-group">
  <label for="spotify_redirect_uri">
    Redirect URI
    <span class="label-hint">(must match exactly in your Spotify App settings)</span>
  </label>
  <input type="text" id="spotify_redirect_uri" name="spotify_redirect_uri"
         placeholder="http://localhost:8000/spotify/callback">
</div>
<div class="form-actions">
  <a href="/spotify/login" class="btn-primary" id="spotify-login-link">
    Connect Spotify Account
  </a>
  <button type="button" id="spotify-logout-btn" class="btn-secondary hidden">
    Disconnect Spotify
  </button>
  <span id="spotify-auth-badge" class="spotify-status-badge"></span>
</div>
```

---

### Modify `static/style.css` — append Spotify auth styles

```css
/* ============================================================
   SPOTIFY TAB — Phase 1 (auth prompt + status badge)
   ============================================================ */

.spotify-auth-prompt {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}
.spotify-auth-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 40px 48px;
  max-width: 480px;
  text-align: center;
}
.spotify-logo   { font-size: 2.5rem; }
.spotify-auth-card h2 { margin: 16px 0 10px; font-size: 1.3rem; }
.spotify-auth-card p  { color: var(--text-secondary); font-size: 0.88rem; line-height: 1.7; margin-bottom: 10px; }
.auth-hint      { font-size: 0.8rem !important; color: var(--text-muted) !important; }
.auth-hint code { background: var(--bg-tertiary); padding: 2px 6px; border-radius: 3px; font-size: 0.78rem; }

.btn-spotify-login {
  display: inline-block;
  margin-top: 20px;
  background: #1db954;
  color: #000;
  font-weight: 700;
  padding: 12px 28px;
  border-radius: 24px;
  font-size: 0.95rem;
  text-decoration: none;
  transition: background 0.15s;
}
.btn-spotify-login:hover { background: #1aa34a; text-decoration: none; }

.spotify-status-badge {
  font-size: 0.8rem;
  padding: 4px 10px;
  border-radius: 12px;
  font-weight: 600;
}
.spotify-status-badge.connected    { background: rgba(29,185,84,0.2); color: #1db954; }
.spotify-status-badge.disconnected { background: var(--bg-tertiary); color: var(--text-muted); }
```

---

### Modify `static/app.js` — append Spotify tab init

```javascript
/* ============================================================
   SPOTIFY — Phase 1: Tab init, auth check, settings status
   ============================================================ */

document.addEventListener('DOMContentLoaded', initSpotifyTab);

async function initSpotifyTab() {
    await checkSpotifyAuth();

    // Handle redirect back from Spotify OAuth
    const params = new URLSearchParams(window.location.search);
    if (params.get('spotify_auth') === 'success') {
        showToast('Spotify connected!', 'success');
        if (params.get('tab') === 'spotify') switchTab('spotify');
        // Clean URL
        history.replaceState({}, '', '/');
    } else if (params.get('spotify_auth') === 'error') {
        showToast('Spotify auth failed. Check credentials in Settings.', 'error');
        history.replaceState({}, '', '/');
    }

    // Logout button
    document.getElementById('spotify-logout-btn')?.addEventListener('click', async () => {
        await fetch('/api/spotify/logout', { method: 'POST' });
        showToast('Spotify disconnected', 'success');
        checkSpotifyAuth();
    });
}

async function checkSpotifyAuth() {
    try {
        const res  = await fetch('/api/spotify/auth-status');
        const data = await res.json();
        const auth = data.authenticated;

        // Spotify tab content
        document.getElementById('spotify-auth-prompt')?.classList.toggle('hidden', auth);
        document.getElementById('spotify-browser')?.classList.toggle('hidden', !auth);

        // Settings tab auth state
        const badge = document.getElementById('spotify-auth-badge');
        if (badge) {
            badge.textContent = auth ? '✓ Connected' : 'Not connected';
            badge.className = `spotify-status-badge ${auth ? 'connected' : 'disconnected'}`;
        }
        document.getElementById('spotify-login-link')?.classList.toggle('hidden', auth);
        document.getElementById('spotify-logout-btn')?.classList.toggle('hidden', !auth);

        // Show redirect URI in auth prompt
        const uriDisplay = document.getElementById('redirect-uri-display');
        if (uriDisplay) {
            const settings = await fetch('/api/settings').then(r => r.json());
            uriDisplay.textContent = settings.spotify_redirect_uri || 'http://localhost:8000/spotify/callback';
        }

        return auth;
    } catch (err) {
        console.error('[Spotify] Auth check failed:', err);
        return false;
    }
}

// Expose so Phase 2 can call it after a fresh auth
window.checkSpotifyAuth = checkSpotifyAuth;
```

---

## API Endpoints (Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/spotify/login` | Redirect to Spotify OAuth |
| `GET` | `/spotify/callback` | Handle OAuth redirect, store tokens |
| `POST` | `/api/spotify/logout` | Clear stored tokens |
| `GET` | `/api/spotify/auth-status` | `{authenticated: bool}` |
| `GET` | `/api/spotify/token` | Return current access token (for SDK in Phase 3) |
| `GET` | `/api/spotify/search?q=&types=` | Search Spotify |
| `GET` | `/api/spotify/artist/{id}/albums` | Get artist's albums |
| `GET` | `/api/spotify/album/{id}/tracks` | Get album tracks |
| `GET` | `/api/spotify/playlists` | Get user's playlists |
| `GET` | `/api/spotify/playlist/{id}/tracks` | Get playlist tracks |
| `POST` | `/api/spotify/player/play-track` | Play a track via Spotify API |
| `POST` | `/api/spotify/player/play-tracks` | Play multiple tracks |
| `POST` | `/api/spotify/player/pause` | Pause |
| `POST` | `/api/spotify/player/resume` | Resume |
| `POST` | `/api/spotify/player/next` | Skip next |
| `POST` | `/api/spotify/player/previous` | Skip previous |
| `GET` | `/api/spotify/player/state` | Current playback state |

---

## Validation Steps

### 1. Settings setup
- Open Settings tab → Spotify section visible with Client ID, Secret, Redirect URI fields.
- Save Client ID + Secret for a Spotify Developer App that has `http://localhost:8000/spotify/callback` as a Redirect URI.

### 2. Auth flow
- Visit `http://localhost:8000` → click "Spotify" tab → auth prompt card appears.
- Click "Login with Spotify" → browser redirects to `accounts.spotify.com`.
- Approve permissions → redirected back to `/spotify/callback?code=...`.
- Toast "Spotify connected!" appears → Spotify tab shows browser skeleton (not auth prompt).
- `sqlite3 sonosweb.db "SELECT access_token IS NOT NULL, refresh_token IS NOT NULL FROM spotify_tokens;"` → `1|1`

### 3. Token auto-refresh
```bash
# Force-expire the token by setting expires_at to the past
sqlite3 sonosweb.db "UPDATE spotify_tokens SET expires_at=0;"
# Then call any API endpoint — it should auto-refresh
curl http://localhost:8000/api/spotify/auth-status
# → {"authenticated": true}   (refresh succeeded)
sqlite3 sonosweb.db "SELECT expires_at > strftime('%s','now') FROM spotify_tokens;"
# → 1  (new token with future expiry)
```

### 4. Metadata endpoints
```bash
curl "http://localhost:8000/api/spotify/search?q=massive+attack&types=artist"
# → {"artists": [{"id": "...", "name": "Massive Attack", ...}]}

# Use an artist ID from the above result:
curl "http://localhost:8000/api/spotify/artist/6FXMGgJwohJLUSr5nVlf9X/albums"
# → {"albums": [{...}, ...]}

# Use an album ID:
curl "http://localhost:8000/api/spotify/album/02frAnSFBJHKYGG5j8RJBO/tracks"
# → {"tracks": [{...}, ...]}

curl "http://localhost:8000/api/spotify/playlists"
# → {"playlists": [...]}
```

### 5. Logout
- Click "Disconnect Spotify" in Settings → "Spotify disconnected" toast.
- Spotify tab reverts to auth prompt.
- `sqlite3 sonosweb.db "SELECT access_token FROM spotify_tokens;"` → empty/NULL.

---

## Notes & Gotchas

**HTTPS requirement:** Spotify only allows `localhost` or HTTPS redirect URIs. For this local-use app, `http://localhost:8000/spotify/callback` works when the user opens the browser on the same machine running the app. If the user accesses the app from a phone or other LAN device, they must initiate the auth from the machine running the app (just for the one-time auth step). After tokens are stored, any LAN device can use the app normally.

**Client Secret in DB:** The Spotify Client Secret is stored as a settings key in SQLite. This is acceptable for a LAN-only personal app. Do not expose the Settings API publicly.

**spotipy vs raw requests:** We use `spotipy` for metadata calls (cleaner API) but raw `requests` for the OAuth token exchange (to avoid spotipy's cache file and auth manager complexity). This hybrid is intentional.

**Scope `streaming`:** Required for Spotify Web Playback SDK (Phase 3). Only works with Spotify Premium. Non-Premium users can still use Sonos playback without issues.

**Spotipy exceptions:** Spotipy raises `spotipy.exceptions.SpotifyException` (e.g. 403 for Premium-only features, 404 for not found). The `services/spotify_client.py` functions should wrap calls in try/except where appropriate. For Phase 1 we've kept it lean; add exception handling in Phases 2/3 where needed.
