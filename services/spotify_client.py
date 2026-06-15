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
    raw = sp.artist_albums(artist_id, include_groups="album,single", limit=50)
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
