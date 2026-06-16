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

    print(f"[DEBUG play_uri] ip={sonos_ip} uri={uri} title={title}")

    # Log group / coordinator info
    try:
        group = player.group
        if group is not None:
            members = ", ".join(m.player_name for m in group.members)
            print(f"[DEBUG play_uri] group={members} coordinator={group.coordinator.player_name}")
        else:
            print(f"[DEBUG play_uri] player={player.player_name} no group")
    except Exception as exc:
        print(f"[DEBUG play_uri] could not read group: {exc!r}")

    # Log transport state before the call
    try:
        before = player.get_current_transport_info()
        print(f"[DEBUG play_uri] transport before: {before.get('current_transport_state', 'UNKNOWN')}")
    except Exception as exc:
        print(f"[DEBUG play_uri] could not read transport before: {exc!r}")
        before = {}

    try:
        player.play_uri(uri)
        print(f"[DEBUG play_uri] play_uri() completed without exception")

        # Verify post-call transport state
        time.sleep(0.5)
        after = player.get_current_transport_info()
        state_after = after.get("current_transport_state", "UNKNOWN")
        print(f"[DEBUG play_uri] transport after: {state_after}")

        # Log current track info
        try:
            track = player.get_current_track_info()
            print(f"[DEBUG play_uri] current track: title={track.get('title')} uri={track.get('uri')} artist={track.get('artist')}")
        except Exception as exc:
            print(f"[DEBUG play_uri] could not read track info: {exc!r}")

        result = {
            "status": "playing" if state_after == "PLAYING" else "unknown",
            "uri": uri,
            "title": title,
            "transport_before": before.get("current_transport_state", ""),
            "transport_after": state_after,
        }
        print(f"[DEBUG play_uri] result={result}")
        return result
    except SoCoException as e:
        print(f"[ERROR play_uri] SoCoException: {e!r}")
        # Some Sonos devices need a stop before a new URI is accepted
        try:
            print(f"[DEBUG play_uri] retrying with stop() first")
            player.stop()
            time.sleep(0.3)
            player.play_uri(uri)
            print(f"[DEBUG play_uri] retry play_uri() completed without exception")
            time.sleep(0.5)
            after = player.get_current_transport_info()
            state_after = after.get("current_transport_state", "UNKNOWN")
            print(f"[DEBUG play_uri] transport after retry: {state_after}")
            return {
                "status": "playing" if state_after == "PLAYING" else "unknown",
                "uri": uri,
                "title": title,
                "transport_after": state_after,
            }
        except Exception as e2:
            print(f"[ERROR play_uri] retry also failed: {e2!r}")
            return {"status": "error", "message": str(e2)}
    except Exception as e:
        print(f"[ERROR play_uri] unexpected exception: {e!r}")
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

    print(f"[DEBUG play_queue] ip={sonos_ip} uri_count={len(uris)}")
    for i, u in enumerate(uris):
        print(f"[DEBUG play_queue]   uri[{i}]={u} title={titles[i] if titles and i < len(titles) else 'N/A'}")

    try:
        player.clear_queue()
        print(f"[DEBUG play_queue] clear_queue() done")

        resolved_titles = []
        for i, uri in enumerate(uris):
            title = (titles[i] if titles and i < len(titles) else f"Track {i+1}")
            resolved_titles.append(title)
            try:
                player.add_uri_to_queue(uri)
                print(f"[DEBUG play_queue] add_uri_to_queue[{i}] ok")
            except Exception as exc:
                print(f"[ERROR play_queue] add_uri_to_queue[{i}] failed: {exc!r}")
                raise

        player.play_from_queue(0)
        print(f"[DEBUG play_queue] play_from_queue(0) done")

        # Verify transport state after
        time.sleep(0.5)
        try:
            transport = player.get_current_transport_info()
            track = player.get_current_track_info()
            print(f"[DEBUG play_queue] transport state: {transport.get('current_transport_state', 'UNKNOWN')}")
            print(f"[DEBUG play_queue] current track: title={track.get('title')} uri={track.get('uri')}")
        except Exception as exc:
            print(f"[DEBUG play_queue] could not verify state: {exc!r}")

        return {
            "status": "playing_queue",
            "track_count": len(uris),
            "first_title": resolved_titles[0] if resolved_titles else uris[0].split('/')[-1],
            "titles": resolved_titles,
            "uris": uris,
        }
    except Exception as e:
        print(f"[ERROR play_queue] exception: {e!r}")
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
