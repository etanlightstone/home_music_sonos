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

def _log_speaker_info(player, label=""):
    """Log speaker identity, group membership, and coordinator."""
    prefix = f"[DEBUG {label}]" if label else "[DEBUG]"
    try:
        print(f"{prefix} player_name={player.player_name} uid={player.uid} ip={player.ip_address}")
    except Exception as exc:
        print(f"{prefix} could not read player name: {exc!r}")
    try:
        group = player.group
        if group is not None:
            members = ", ".join(f"{m.player_name} ({m.ip_address})" for m in group.members)
            coord = group.coordinator
            print(f"{prefix} group members={members}")
            print(f"{prefix} coordinator={coord.player_name} ip={coord.ip_address}")
        else:
            print(f"{prefix} no group")
    except Exception as exc:
        print(f"{prefix} could not read group: {exc!r}")


def _coordinator(ip: str) -> SoCo:
    """Return the group coordinator for the speaker at ip, falling back to the speaker itself."""
    player = _player(ip)
    try:
        group = player.group
        if group is not None:
            coord = group.coordinator
            print(f"[DEBUG _coordinator] player={player.player_name} coordinator={coord.player_name} ({coord.ip_address})")
            return coord
    except Exception as exc:
        print(f"[DEBUG _coordinator] could not get coordinator for {ip}: {exc!r}")
    return player


def play_queue(sonos_ip: str, uris: list, titles: list = None) -> dict:
    """
    Clear the Sonos queue, load all URIs, and start playing from track 1.
    uris: list of http:// URLs in play order.
    titles: optional list of display titles (same length as uris).
    """
    if not uris:
        return {"status": "error", "message": "No URIs provided"}

    player = _coordinator(sonos_ip)  # always target the coordinator for queue ops

    print(f"[DEBUG play_queue] ip={sonos_ip} uri_count={len(uris)} using coordinator={player.player_name} ({player.ip_address})")
    _log_speaker_info(player, "play_queue")
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


# ── Spotify-specific playback ──────────────────────────────────

# Spotify service descriptor for Sonos DIDL-Lite metadata.
# SA_RINCON{service_type}_ where service_type=3079 for Spotify
_SPOTIFY_SERVICE_DESC = "SA_RINCON3079_"

# Spotify service ID for URI parameters (sid=12 for SoCo/MusicService)
_SPOTIFY_SERVICE_ID = 12


def _spotify_didl_metadata(track_uri: str, title: str) -> str:
    """Build DIDL-Lite metadata XML for a Spotify track on Sonos."""
    escaped_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return (
        '<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/"'
        ' xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"'
        ' xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/"'
        ' xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        '<item id="00030020{uri}" parentID="00030020{uri}" restricted="true">'
        "<dc:title>{title}</dc:title>"
        "<upnp:class>object.item.audioItem.musicTrack</upnp:class>"
        '<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
        "{service}</desc></item></DIDL-Lite>"
    ).format(uri=track_uri, title=escaped_title, service=_SPOTIFY_SERVICE_DESC)


def _spotify_sonos_uri(spotify_track_uri: str) -> str:
    """Convert spotify:track:TRACKID to x-sonos-spotify URI with correct sid."""
    track_id = spotify_track_uri.split(":")[-1]
    return f"x-sonos-spotify:spotify:track:{track_id}?sid={_SPOTIFY_SERVICE_ID}&sn=0"


def play_spotify_queue(sonos_ip: str, spotify_uris: list, titles: list = None) -> dict:
    """
    Queue multiple Spotify tracks on a Sonos speaker using AddURIToQueue
    with proper DIDL-Lite metadata for each track.
    """
    if not spotify_uris:
        return {"status": "error", "message": "No tracks provided"}

    player = _coordinator(sonos_ip)

    print(f"[DEBUG play_spotify_queue] ip={sonos_ip} track_count={len(spotify_uris)}")
    _log_speaker_info(player, "play_spotify_queue")

    try:
        player.clear_queue()
        print(f"[DEBUG play_spotify_queue] clear_queue() done")

        for i, su in enumerate(spotify_uris):
            sonos_uri = _spotify_sonos_uri(su)
            title = (titles[i] if titles and i < len(titles) else f"Track {i+1}")
            metadata = _spotify_didl_metadata(sonos_uri, title)

            print(f"[DEBUG play_spotify_queue]   [{i}] uri={sonos_uri} title={title}")

            player.avTransport.AddURIToQueue([
                ("InstanceID", 0),
                ("EnqueuedURI", sonos_uri),
                ("EnqueuedURIMetaData", metadata),
                ("DesiredFirstTrackNumberEnqueued", 0),
                ("EnqueueAsNext", 1),
            ])
            print(f"[DEBUG play_spotify_queue]   [{i}] ok")

        player.play_from_queue(0)
        print(f"[DEBUG play_spotify_queue] play_from_queue(0) done")

        time.sleep(0.5)
        try:
            transport = player.get_current_transport_info()
            track = player.get_current_track_info()
            print(f"[DEBUG play_spotify_queue] transport state: {transport.get('current_transport_state', 'UNKNOWN')}")
            print(f"[DEBUG play_spotify_queue] current track: title={track.get('title')} uri={track.get('uri')}")
        except Exception as exc:
            print(f"[DEBUG play_spotify_queue] could not verify state: {exc!r}")

        resolved_titles = titles or [f"Track {i+1}" for i in range(len(spotify_uris))]
        result = {
            "status": "playing",
            "track_count": len(spotify_uris),
            "first_title": resolved_titles[0] if resolved_titles else spotify_uris[0].split(":")[-1],
            "titles": resolved_titles,
            "uris": [_spotify_sonos_uri(su) for su in spotify_uris],
        }
        print(f"[DEBUG play_spotify_queue] result={result}")
        return result

    except Exception as e:
        print(f"[ERROR play_spotify_queue] exception: {e!r}")
        return {"status": "error", "message": str(e)}


def play_spotify_uri(sonos_ip: str, spotify_uri: str, title: str) -> dict:
    """
    Play a Spotify track on a Sonos speaker using SetAVTransportURI
    with proper DIDL-Lite metadata containing the Spotify service descriptor.

    This is necessary because SoCo's generic play_uri() generates metadata
    with the radio service descriptor (SA_RINCON65031_) rather than
    Spotify's (SA_RINCON3079_), causing the Sonos to remain STOPPED.
    """
    player = _coordinator(sonos_ip)

    sonos_uri = _spotify_sonos_uri(spotify_uri)
    metadata = _spotify_didl_metadata(sonos_uri, title)

    print(f"[DEBUG play_spotify_uri] spotify_uri={spotify_uri}")
    print(f"[DEBUG play_spotify_uri] sonos_uri={sonos_uri}")
    print(f"[DEBUG play_spotify_uri] title={title}")
    print(f"[DEBUG play_spotify_uri] metadata={metadata[:300]}...")

    _log_speaker_info(player, "play_spotify_uri")

    # Log transport state before
    try:
        before = player.get_current_transport_info()
        print(f"[DEBUG play_spotify_uri] transport before: {before.get('current_transport_state', 'UNKNOWN')}")
    except Exception as exc:
        print(f"[DEBUG play_spotify_uri] could not read transport before: {exc!r}")
        before = {}

    try:
        player.avTransport.SetAVTransportURI([
            ("InstanceID", 0),
            ("CurrentURI", sonos_uri),
            ("CurrentURIMetaData", metadata),
        ])
        print(f"[DEBUG play_spotify_uri] SetAVTransportURI completed without exception")

        # Now start playback
        player.avTransport.Play([("InstanceID", 0), ("Speed", 1)])
        print(f"[DEBUG play_spotify_uri] Play() completed")

        # Verify post-call transport state
        time.sleep(0.5)
        after = player.get_current_transport_info()
        state_after = after.get("current_transport_state", "UNKNOWN")
        print(f"[DEBUG play_spotify_uri] transport after: {state_after}")

        try:
            track = player.get_current_track_info()
            print(f"[DEBUG play_spotify_uri] current track: title={track.get('title')} uri={track.get('uri')} artist={track.get('artist')}")
        except Exception as exc:
            print(f"[DEBUG play_spotify_uri] could not read track info: {exc!r}")

        result = {
            "status": "playing" if state_after == "PLAYING" else "unknown",
            "uri": sonos_uri,
            "title": title,
            "spotify_uri": spotify_uri,
            "transport_before": before.get("current_transport_state", ""),
            "transport_after": state_after,
        }
        print(f"[DEBUG play_spotify_uri] result={result}")
        return result

    except Exception as e:
        print(f"[ERROR play_spotify_uri] exception: {e!r}")
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
