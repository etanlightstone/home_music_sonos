"""
Sonos controller using soco.
All public functions are synchronous — wrap in asyncio.run_in_executor
when calling from async FastAPI route handlers.
"""

import time
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

    # Log transport state before the call
    try:
        before = player.get_current_transport_info()
    except Exception:
        before = {}

    try:
        player.play_uri(uri)

        # Verify post-call transport state
        time.sleep(0.5)
        after = player.get_current_transport_info()
        state_after = after.get("current_transport_state", "UNKNOWN")

        result = {
            "status": "playing" if state_after == "PLAYING" else "unknown",
            "uri": uri,
            "title": title,
            "transport_before": before.get("current_transport_state", ""),
            "transport_after": state_after,
        }
        return result
    except SoCoException as e:
        # Some Sonos devices need a stop before a new URI is accepted
        try:
            player.stop()
            time.sleep(0.3)
            player.play_uri(uri)
            time.sleep(0.5)
            after = player.get_current_transport_info()
            state_after = after.get("current_transport_state", "UNKNOWN")
            return {
                "status": "playing" if state_after == "PLAYING" else "unknown",
                "uri": uri,
                "title": title,
                "transport_after": state_after,
            }
        except Exception as e2:
            return {"status": "error", "message": str(e2)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Folder / queue playback ──────────────────────────────────

def play_queue(sonos_ip: str, uris: list, titles: list = None) -> dict:
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
        resolved_titles = []
        for i, uri in enumerate(uris):
            title = (titles[i] if titles and i < len(titles) else f"Track {i+1}")
            resolved_titles.append(title)
            player.add_uri_to_queue(uri)
        player.play_from_queue(0)
        return {
            "status": "playing_queue",
            "track_count": len(uris),
            "first_title": resolved_titles[0] if resolved_titles else uris[0].split('/')[-1],
            "titles": resolved_titles,
            "uris": uris,
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

def set_volume(sonos_ip: str, level: int) -> dict:
    player = _player(sonos_ip)
    try:
        level = max(0, min(100, int(level)))
        group = player.group
        if group is not None:
            group.volume = level
        else:
            player.volume = level
        return {"status": "ok", "volume": level}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_volume(sonos_ip: str) -> dict:
    player = _player(sonos_ip)
    try:
        group = player.group
        if group is not None:
            return {"volume": group.volume}
        return {"volume": player.volume}
    except Exception as e:
        return {"volume": 0, "error": str(e)}


def get_state(sonos_ip: str) -> dict:
    """
    Returns current transport state and track info.
    Useful for syncing the UI to what Sonos is actually playing.
    """
    player = _player(sonos_ip)
    try:
        transport = player.get_current_transport_info()
        track     = player.get_current_track_info()
        group = player.group
        if group is not None:
            vol = group.volume
        else:
            vol = player.volume
        return {
            "state":    transport.get("current_transport_state", "UNKNOWN"),
            "title":    track.get("title", ""),
            "artist":   track.get("artist", ""),
            "album":    track.get("album", ""),
            "position": track.get("position", ""),
            "duration": track.get("duration", ""),
            "uri":      track.get("uri", ""),
            "tracknum": track.get("tracknum", ""),
            "volume":   vol,
        }
    except Exception as e:
        return {
            "state": "UNKNOWN",
            "title": "",
            "error": str(e),
        }
