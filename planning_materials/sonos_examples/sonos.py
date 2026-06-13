#!/usr/bin/env python3
"""
Sonos API Skill — control Sonos players via soco (Sonos Controller API).

Requires: pip3 install soco

Usage:
    python3 sonos.py discover                  # Find all Sonos players on network
    python3 sonos.py state [player_ip]         # Get current playback state
    python3 sonos.py play <uri> [player_ip]    # Play an audio stream/URI
    python3 sonos.py play-spotify <spotify-uri> [player_ip]  # Play a Spotify track (auto-converts URI)
    python3 sonos.py play-radio <url> [player_ip]  # Play a radio stream
    python3 sonos.py play-music <uri> [player_ip]  # Play a music file/URI
    python3 sonos.py play-dropbox <dropbox-link> [player_ip]  # Play audio from a Dropbox link
    python3 sonos.py pause [player_ip]         # Pause playback
    python3 sonos.py stop [player_ip]          # Stop playback
    python3 sonos.py next [player_ip]          # Skip to next track
    python3 sonos.py prev [player_ip]          # Go to previous track
    python3 sonos.py seek <seconds> [player_ip]  # Seek to position in seconds
    python3 sonos.py volume <level> [player_ip]  # Set volume (0-100)
    python3 sonos.py volume-up [player_ip]     # Increase volume by 5
    python3 sonos.py volume-down [player_ip]   # Decrease volume by 5
    python3 sonos.py mute [player_ip]          # Toggle mute
    python3 sonos.py unmute [player_ip]        # Unmute (was "unmut")
    python3 sonos.py group <player_ip> [player_ip, ...]  # Group players
    python3 sonos.py ungroup <player_ip>       # Ungroup a player from its group
    python3 sonos.py set-bass <level> [player_ip]  # Set bass (-15 to +15)
    python3 sonos.py set-treble <level> [player_ip]  # Set treble (-15 to +15)
    python3 sonos.py EQ <bass> <treble> [player_ip]  # Set both bass and treble

Defaults:
    Default player is 10.0.1.90 (Beam speaker).
    Override with SONOS_PLAYER_IP env var or pass IP as last argument.

Author: Openadmin
"""

import sys
import os
import json
import re
import urllib3
import requests

try:
    import soco
    from soco.core import SoCo
except ImportError:
    print("Error: soco package not installed. Run: pip3 install soco")
    sys.exit(1)

# Default Sonos player — override with SONOS_PLAYER_IP env var or command-line arg
DEFAULT_PLAYER_IP = os.environ.get("SONOS_PLAYER_IP", "10.0.1.90")


SONOS_IP = "10.0.1.90"


def get_player(ip):
    """Get a SoCo player instance."""
    return SoCo(ip)


def convert_spotify_uri(uri: str) -> str:
    """Convert a Spotify URI (spotify:track:xxx) to Sonos URI (x-sonos-spotify:spotify%3atrack%3axxx)."""
    track_id = uri.split(":")[-1]
    return f"x-sonos-spotify:spotify%3atrack%3a{track_id}"


def is_spotify_uri(uri: str) -> bool:
    """Check if a URI is a Spotify URI."""
    return uri.startswith("spotify:")


def is_dropbox_link(uri: str) -> bool:
    """Check if a URI is a Dropbox sharing link (www, dl, or just dropbox.com)."""
    return bool(re.match(r'https?://(www\.|dl\.)?dropbox\.com/', uri))


def convert_dropbox_to_direct(uri: str) -> str:
    """Convert a Dropbox sharing link to a direct download link.

    e.g. https://www.dropbox.com/scl/fi/... → https://dl.dropbox.com/scl/fi/...
    """
    return re.sub(r'https?://(www\.)?dropbox\.com/', 'https://dl.dropbox.com/', uri)


def resolve_dropbox_redirect(uri: str, timeout=10, max_redirects=5) -> str:
    """Resolve Dropbox redirect to get the final direct download URL.

    Dropbox's dl.dropbox.com links often redirect to a signed/signed URL.
    We follow redirects (without following them automatically) to get the
    real URL that Sonos can use.
    """
    uri = convert_dropbox_to_direct(uri)
    try:
        resp = requests.head(uri, allow_redirects=True, timeout=timeout, stream=True)
        final_url = resp.url
        # If redirects happened, return the final URL
        if resp.url != uri:
            return resp.url
        # No redirect — the dl link itself works
        return uri
    except requests.exceptions.RequestException:
        # If HEAD fails, try GET to see if it works anyway
        try:
            resp = requests.get(uri, timeout=timeout, stream=True)
            final_url = resp.url
            resp.close()
            if resp.url != uri:
                return resp.url
            return uri
        except requests.exceptions.RequestException:
            # If all resolution fails, return the dl link — Sonos may handle it
            return uri


def play_dropbox(ip, uri):  # noqa: C901 (complex function)
    """Play audio from a Dropbox link, resolving redirects as needed."""
    player = get_player(ip)
    # Resolve the Dropbox link to a direct download URL
    direct_url = resolve_dropbox_redirect(uri)
    try:
        player.play_uri(direct_url)
        return f"Playing (Dropbox): {direct_url}"
    except Exception as e:
        # Fallback: try the original dl link in case redirect resolution failed
        dl_link = convert_dropbox_to_direct(uri)
        try:
            player.play_uri(dl_link)
            return f"Playing (Dropbox, fallback): {dl_link}"
        except Exception as e2:
            return f"Play error: {e2}"


def discover():
    """Discover Sonos players on the network."""
    players = []
    try:
        # soco.discover() uses SSDP multicast to find all players
        found = soco.discover()
        if found:
            for p in sorted(found, key=lambda x: x.player_name):
                players.append({
                    "ip": p.ip_address,
                    "name": p.player_name,
                    "uuid": p.uid
                })
    except Exception as e:
        print(f"Discovery error: {e}")
    return players


def get_state(ip):
    """Get current playback state and track info."""
    player = get_player(ip)
    transport = player.get_current_transport_info()
    volume = player.volume
    mute = player.mute
    play_mode = player.play_mode

    try:
        track = player.get_current_track_info()
    except Exception:
        track = {}

    info = {
        "player_name": player.player_name,
        "state": transport.get("current_transport_state", "UNKNOWN"),
        "status": transport.get("current_transport_status", "UNKNOWN"),
        "speed": transport.get("current_transport_speed", "1"),
        "volume": volume,
        "mute": mute,
        "play_mode": play_mode,
        "title": track.get("title", "Unknown"),
        "artist": track.get("artist", ""),
        "album": track.get("album", ""),
        "position": track.get("position", "0:00:00"),
        "duration": track.get("duration", "0:00:00"),
        "uri": track.get("uri", ""),
    }
    return json.dumps(info, indent=2)


def play(ip, uri, metadata=""):
    """Set the URI and start playback. Auto-converts Spotify URIs."""
    player = get_player(ip)

    # Auto-convert Spotify URIs to Sonos format
    if is_spotify_uri(uri):
        uri = convert_spotify_uri(uri)

    try:
        player.play_uri(uri)
        return f"Playing: {uri}"
    except Exception as e:
        # Some Sonos devices need a stop+pause cycle before playing
        try:
            player.stop()
            import time; time.sleep(0.5)
            player.play_uri(uri)
            return f"Playing: {uri}"
        except Exception as e2:
            return f"Play error: {e2}"


def play_radio(ip, url):
    """Play a radio stream."""
    player = get_player(ip)
    # Sonos radio streams use x-rincon-mp3radio:// prefix
    uri = f"x-rincon-mp3radio://{url}"
    metadata = f'''<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"
        xmlns:dc="http://purl.org/dc/elements/1.1/"
        xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">
        <item id="0" parentID="-1" restricted="true">
            <dc:title>Radio Stream</dc:title>
            <upnp:class>object.item.audioItem.musicTrack</upnp:class>
            <res>{uri}</res>
        </item>
    </DIDL-Lite>'''
    return play(ip, uri, metadata)


def play_music(ip, uri):
    """Play a music file/URI."""
    return play(ip, uri)


def play_dropbox_cmd(ip, uri):
    """Play audio from a Dropbox link (wrapper for CLI)."""
    return play_dropbox(ip, uri)


def pause(ip):
    """Pause playback."""
    player = get_player(ip)
    try:
        player.pause()
        return "Playback paused"
    except Exception:
        state = player.get_current_transport_info()['current_transport_state']
        return f"Already {state.lower()}"


def stop(ip):
    """Stop playback."""
    player = get_player(ip)
    try:
        player.stop()
        return "Playback stopped"
    except Exception:
        state = player.get_current_transport_info()['current_transport_state']
        return f"Already {state.lower()}"


def next_track(ip):
    """Skip to next track."""
    player = get_player(ip)
    try:
        player.next()
        return "Skipped to next track"
    except Exception:
        return "No next track available"


def prev_track(ip):
    """Go to previous track."""
    player = get_player(ip)
    try:
        player.previous()
        return "Went to previous track"
    except Exception:
        return "No previous track available"


def seek(ip, seconds):
    """Seek to a position in seconds."""
    player = get_player(ip)
    try:
        player.seek(f"0:{int(seconds//60):02d}:{int(seconds%60):02d}")
        return f"Seeked to {seconds}s"
    except Exception:
        return "Seek failed (no track playing)"


def set_volume(ip, level):
    """Set volume for a player (0-100)."""
    player = get_player(ip)
    level = max(0, min(100, int(level)))
    player.volume = level
    return f"Volume set to {level}"


def volume_up(ip):
    """Increase volume by 5."""
    player = get_player(ip)
    current = player.volume
    set_volume(ip, current + 5)
    return f"Volume up to {player.volume}"


def volume_down(ip):
    """Decrease volume by 5."""
    player = get_player(ip)
    current = player.volume
    set_volume(ip, current - 5)
    return f"Volume down to {player.volume}"


def mute_toggle(ip):
    """Toggle mute."""
    player = get_player(ip)
    player.mute = not player.mute
    return f"Mute: {player.mute}"


def unmute(ip):
    """Unmute."""
    player = get_player(ip)
    player.mute = False
    return "Unmuted"


def group_players(coordinator_ip, members):
    """Group multiple players together."""
    coordinator = get_player(coordinator_ip)
    for member_ip in members:
        if member_ip != coordinator_ip:
            member = get_player(member_ip)
            try:
                member.join(coordinator)
            except Exception as e:
                print(f"Error grouping {member_ip}: {e}")
    return f"Grouped {coordinator_ip} with {[m for m in members if m != coordinator_ip]}"


def ungroup_player(ip):
    """Ungroup a player from its group."""
    player = get_player(ip)
    player.unjoin()
    return f"Ungrouped player {ip}"


def set_bass(ip, level):
    """Set bass level (-15 to +15)."""
    player = get_player(ip)
    level = max(-15, min(15, int(level)))
    player.bass = level
    return f"Bass set to {level}"


def set_treble(ip, level):
    """Set treble level (-15 to +15)."""
    player = get_player(ip)
    level = max(-15, min(15, int(level)))
    player.treble = level
    return f"Treble set to {level}"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "discover":
        players = discover()
        if players:
            print(f"Found {len(players)} Sonos player(s):")
            for p in players:
                print(f"  {p['name']} ({p['ip']}) — UUID: {p['uuid']}")
        else:
            print("No Sonos players found on the network.")
            print("Make sure the machine running this script is on the same network as your Sonos devices.")
            print(f"Default player is {DEFAULT_PLAYER_IP} — use 'sonos.py state {DEFAULT_PLAYER_IP}' to test.")
        return

    # Get player IP — use DEFAULT_PLAYER_IP unless overridden on command line
    ip = DEFAULT_PLAYER_IP
    if command in ("play", "play-radio", "play-music", "play-spotify", "play-dropbox"):
        if len(sys.argv) >= 3:
            ip = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PLAYER_IP
        else:
            print("Usage: sonos.py play <uri> [player_ip]")
            return
    elif command in ("pause", "stop", "next", "prev", "mute", "unmut", "unmute", "volume-up", "volume-down", "state"):
        ip = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PLAYER_IP
    elif command == "seek":
        ip = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PLAYER_IP
    elif command == "volume":
        ip = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PLAYER_IP
    elif command == "group":
        ip = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PLAYER_IP
    elif command == "ungroup":
        ip = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PLAYER_IP
    elif command in ("set-bass", "set-treble"):
        ip = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_PLAYER_IP
    elif command == "EQ":
        ip = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_PLAYER_IP

    if not ip:
        print(f"Error: No player IP specified. Set SONOS_PLAYER_IP or pass as argument.")
        sys.exit(1)

    if command == "play" or command == "play-radio" or command == "play-spotify":
        uri = sys.argv[2]
        if command == "play-radio":
            print(play_radio(ip, uri))
        elif command == "play-spotify":
            print(play(ip, uri))
        else:
            print(play(ip, uri))
    elif command == "play-music":
        uri = sys.argv[2]
        print(play_music(ip, uri))
    elif command == "play-dropbox":
        uri = sys.argv[2]
        print(play_dropbox_cmd(ip, uri))
    elif command == "pause":
        print(pause(ip))
    elif command == "stop":
        print(stop(ip))
    elif command == "next":
        print(next_track(ip))
    elif command == "prev":
        print(prev_track(ip))
    elif command == "seek":
        seconds = int(sys.argv[2])
        print(seek(ip, seconds))
    elif command == "state":
        print(get_state(ip))
    elif command == "volume":
        level = sys.argv[2]
        print(set_volume(ip, level))
    elif command == "volume-up":
        print(volume_up(ip))
    elif command == "volume-down":
        print(volume_down(ip))
    elif command == "mute":
        print(mute_toggle(ip))
    elif command == "unmut" or command == "unmute":
        print(unmute(ip))
    elif command == "group":
        members = sys.argv[3:] if len(sys.argv) > 3 else []
        print(group_players(ip, members))
    elif command == "ungroup":
        print(ungroup_player(ip))
    elif command == "set-bass":
        print(set_bass(ip, sys.argv[2]))
    elif command == "set-treble":
        print(set_treble(ip, sys.argv[2]))
    elif command == "EQ":
        print(set_bass(ip, sys.argv[2]))
        print(set_treble(ip, sys.argv[3]))
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
