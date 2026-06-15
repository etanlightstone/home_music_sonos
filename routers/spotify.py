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
