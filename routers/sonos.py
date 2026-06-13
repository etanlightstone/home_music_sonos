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
    path: str
    name: Optional[str] = ""


class PlayFolderRequest(BaseModel):
    path: str


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
