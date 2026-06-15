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


# ── Pin/Unpin endpoints ──────────────────────────────────────

class PinRequest(BaseModel):
    item_type:   str
    spotify_id:  str
    name:        str
    artist_id:   Optional[str] = None
    artist_name: Optional[str] = None
    album_id:    Optional[str] = None
    album_name:  Optional[str] = None
    track_number: Optional[int] = None
    disc_number:  Optional[int] = 1
    duration_ms:  Optional[int] = None
    image_url:    Optional[str] = None


@router.post("/pin")
async def pin_item(req: PinRequest):
    from database import get_db
    conn = get_db()

    if req.item_type == "album":
        loop = asyncio.get_event_loop()
        tracks = await loop.run_in_executor(None, sc.get_album_tracks, req.spotify_id)
        with conn:
            conn.execute("""
                INSERT OR IGNORE INTO spotify_pins
                  (item_type, spotify_id, name, artist_id, artist_name,
                   album_id, album_name, image_url)
                VALUES ('album', ?, ?, ?, ?, ?, ?, ?)
            """, (req.spotify_id, req.name, req.artist_id, req.artist_name,
                  req.spotify_id, req.name, req.image_url))
            for t in tracks:
                conn.execute("""
                    INSERT OR IGNORE INTO spotify_pins
                      (item_type, spotify_id, name, artist_id, artist_name,
                       album_id, album_name, track_number, disc_number, duration_ms, image_url)
                    VALUES ('track', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (t["id"], t["name"], t.get("artist_id"), t.get("artist_name"),
                      t["album_id"], t["album_name"],
                      t.get("track_number"), t.get("disc_number", 1),
                      t.get("duration_ms"), t.get("image_url")))
        conn.close()
        return {"status": "pinned", "type": "album", "tracks_added": len(tracks)}

    else:
        with conn:
            conn.execute("""
                INSERT OR IGNORE INTO spotify_pins
                  (item_type, spotify_id, name, artist_id, artist_name,
                   album_id, album_name, track_number, disc_number, duration_ms, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (req.item_type, req.spotify_id, req.name,
                  req.artist_id, req.artist_name,
                  req.album_id, req.album_name,
                  req.track_number, req.disc_number or 1,
                  req.duration_ms, req.image_url))
        conn.close()
        return {"status": "pinned", "type": req.item_type}


@router.delete("/pin/{spotify_id}")
def unpin_item(spotify_id: str):
    from database import get_db
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM spotify_pins WHERE spotify_id=?", (spotify_id,))
    conn.close()
    return {"status": "unpinned", "spotify_id": spotify_id}


@router.get("/pin/check/{spotify_id}")
def check_pinned(spotify_id: str):
    from database import get_db
    conn = get_db()
    row = conn.execute(
        "SELECT id, item_type FROM spotify_pins WHERE spotify_id=? LIMIT 1",
        (spotify_id,)
    ).fetchone()
    conn.close()
    return {"pinned": row is not None, "type": dict(row)["item_type"] if row else None}


# ── Pinned library browse endpoints ─────────────────────────

@router.get("/pins/artists")
def pinned_artists():
    from database import get_db
    conn = get_db()
    rows = conn.execute("""
        SELECT spotify_id, name, image_url FROM spotify_pins WHERE item_type='artist'
        UNION
        SELECT DISTINCT artist_id AS spotify_id, artist_name AS name, image_url
          FROM spotify_pins WHERE item_type IN ('album','track') AND artist_id IS NOT NULL
        ORDER BY name COLLATE NOCASE
    """).fetchall()
    conn.close()
    seen = set()
    artists = []
    for r in rows:
        d = dict(r)
        if d["spotify_id"] not in seen:
            seen.add(d["spotify_id"])
            artists.append(d)
    return {"artists": artists}


@router.get("/pins/albums/{artist_id}")
def pinned_albums(artist_id: str):
    from database import get_db
    conn = get_db()
    artist_pin = conn.execute(
        "SELECT * FROM spotify_pins WHERE item_type='artist' AND spotify_id=?",
        (artist_id,)
    ).fetchone()
    rows = conn.execute("""
        SELECT DISTINCT album_id AS spotify_id, album_name AS name, image_url
          FROM spotify_pins WHERE artist_id=? AND album_id IS NOT NULL
        ORDER BY name COLLATE NOCASE
    """, (artist_id,)).fetchall()
    conn.close()
    return {
        "artist_id":    artist_id,
        "albums":       [dict(r) for r in rows],
        "has_artist_pin": artist_pin is not None,
        "live_browse_available": artist_pin is not None and len(rows) == 0,
    }


@router.get("/pins/tracks/{album_id}")
def pinned_tracks(album_id: str):
    from database import get_db
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM spotify_pins
          WHERE album_id=? AND item_type='track'
          ORDER BY disc_number, track_number
    """, (album_id,)).fetchall()
    conn.close()
    return {"album_id": album_id, "tracks": [dict(r) for r in rows]}
