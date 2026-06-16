import asyncio
import soco
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
    path: str
    name: Optional[str] = ""


class PlayFolderRequest(BaseModel):
    path: str


class SetVolumeRequest(BaseModel):
    volume: int


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
    from routers.files import folder_files
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
        "first_title": result.get("first_title", titles[0] if titles else ""),
        "titles": result.get("titles", titles or []),
        "uris": result.get("uris", uris),
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


@router.get("/volume")
async def get_volume():
    sonos_ip = _get_sonos_ip()
    loop     = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.get_volume, sonos_ip)


@router.post("/set-volume")
async def set_volume(req: SetVolumeRequest):
    sonos_ip = _get_sonos_ip()
    loop     = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sc.set_volume, sonos_ip, req.volume)


# ── Diagnostics ────────────────────────────────────────────────

@router.get("/debug")
async def debug_sonos():
    """Dump Sonos speaker info, group, and available music services."""
    from soco import discover
    sonos_ip = _get_sonos_ip()
    info = {"target_ip": sonos_ip}

    # Discover all speakers
    try:
        speakers = discover()
        if speakers:
            info["discovered"] = [
                {"name": s.player_name, "ip": s.ip_address, "uid": s.uid}
                for s in speakers
            ]
        else:
            info["discovered"] = []
    except Exception as exc:
        info["discovered_error"] = str(exc)

    # Detailed info for the target speaker
    player = soco.SoCo(sonos_ip)
    try:
        info["player_name"] = player.player_name
        info["uid"] = player.uid
        info["ip"] = player.ip_address
    except Exception as exc:
        info["player_error"] = str(exc)

    try:
        group = player.group
        if group is not None:
            coord = group.coordinator
            info["coordinator"] = {"name": coord.player_name, "ip": coord.ip_address, "uid": coord.uid}
            info["group_members"] = [
                {"name": m.player_name, "ip": m.ip_address}
                for m in group.members
            ]
    except Exception as exc:
        info["group_error"] = str(exc)

    # List music services
    try:
        services = player.music_services
        info["music_services"] = [
            {"name": svc.name, "sid": svc.sid, "capabilities": svc.capabilities}
            for svc in services
        ]
    except Exception as exc:
        info["music_services_error"] = str(exc)

    # Check if Spotify (sid=9) is linked
    try:
        spotify_svc = player.get_music_service(9)
        info["spotify_service"] = {
            "name": spotify_svc.name,
            "auth": spotify_svc.authentication,
            "policy": spotify_svc.policy,
            "present": spotify_svc.present,
        }
    except Exception as exc:
        info["spotify_service_error"] = str(exc)

    return info


# ── Spotify-on-Sonos playback ─────────────────────────────────

def _spotify_uri_to_sonos(spotify_track_uri: str, sid: int = 9, flags: int = 8224, sn: int = 7) -> str:
    track_id = spotify_track_uri.split(":")[-1]
    return f"x-sonos-spotify:spotify:track:{track_id}?sid={sid}&flags={flags}&sn={sn}"


class PlaySpotifyTrackOnSonosRequest(BaseModel):
    spotify_uri: str
    name:        str = ""


class PlaySpotifyAlbumOnSonosRequest(BaseModel):
    track_uris:  list[str]
    names:       list[str]
    album_name:  str = ""


@router.post("/play-spotify-track")
async def play_spotify_track_on_sonos(req: PlaySpotifyTrackOnSonosRequest):
    sonos_ip  = _get_sonos_ip()
    sonos_uri = _spotify_uri_to_sonos(req.spotify_uri)
    title     = req.name or req.spotify_uri.split(":")[-1]

    print(f"[DEBUG play_spotify_track_on_sonos] spotify_uri={req.spotify_uri}")
    print(f"[DEBUG play_spotify_track_on_sonos] sonos_uri={sonos_uri}")
    print(f"[DEBUG play_spotify_track_on_sonos] sonos_ip={sonos_ip}")
    print(f"[DEBUG play_spotify_track_on_sonos] title={title}")

    # Use queue-based approach (add_uri_to_queue + play_from_queue) instead of
    # play_uri(), because play_uri() uses SetAVTransportURI which doesn't
    # transition from STOPPED for Spotify music-service URIs.
    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, sc.play_queue, sonos_ip, [sonos_uri], [title])

    print(f"[DEBUG play_spotify_track_on_sonos] result={result}")

    return {**result, "spotify_uri": req.spotify_uri, "sonos_uri": sonos_uri, "title": title}


@router.post("/play-spotify-album")
async def play_spotify_album_on_sonos(req: PlaySpotifyAlbumOnSonosRequest):
    if not req.track_uris:
        return {"status": "error", "message": "No tracks provided"}

    sonos_ip   = _get_sonos_ip()
    sonos_uris = [_spotify_uri_to_sonos(u) for u in req.track_uris]
    titles     = req.names if req.names else [f"Track {i+1}" for i in range(len(sonos_uris))]

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, sc.play_queue, sonos_ip, sonos_uris, titles)
    return {
        **result,
        "album": req.album_name,
        "track_count": len(sonos_uris),
        "first_title": titles[0] if titles else "",
    }
