# Sonos Control Skill

Control Sonos players on your local network via the **soco** library (Sonos Controller API).

## Setup

The script lives at: `/root/openadmin/.pi/skills/sonos/sonos.py`

**Prerequisite:** `pip3 install soco` (already installed)

**Important:** This machine must be on the same network as your Sonos devices. SSDP discovery may not work from containers.

**Default player:** `10.0.1.90` (Beam speaker). Override with `SONOS_PLAYER_IP` env var or pass IP as last argument.

## Known Device

- **Beam speaker** at `10.0.1.90` (Sonos Beam soundbar, UID: RINCON_347E5C9EA80701400)

## Commands

### Discover Players
```bash
python3 sonos.py discover
```
Scans the local network via SSDP. May not work in containers — use IP directly.

### State
```bash
python3 sonos.py state [player_ip]
```
Returns JSON with: player name, state, status, volume, mute, play mode, track info (title, artist, album, position, duration).

### Play Audio
```bash
python3 sonos.py play <uri> [player_ip]
python3 sonos.py play-spotify <spotify-uri> [player_ip]
python3 sonos.py play-radio <url> [player_ip]
python3 sonos.py play-music <uri> [player_ip]
python3 sonos.py play-dropbox <dropbox-link> [player_ip]
```
Sets the audio URI and starts playback. Supports:
- **Radio streams:** `x-rincon-mp3radio://http://stream-url`
- **Spotify tracks/playlists:** Auto-converts `spotify:track:xxx` → `x-sonos-spotify:spotify%3atrack%3axxx` (URL-encoded)
- **Local audio files:** `http://server/music.mp3`
- **Dropbox links:** Converts sharing links → direct download links, resolves redirects

**Spotify URIs:** Use `play-spotify` for Spotify URIs — the script auto-converts `spotify:track:3dPQuX8Gs42Y7b454ybpMR` to the Sonos-compatible format with URL-encoded colons (`%3a`).

**Dropbox links:** Use `play-dropbox` for Dropbox sharing links. The script automatically:
1. Converts `www.dropbox.com/scl/fi/...` → `dl.dropbox.com/scl/fi/...`
2. Resolves any redirects to get the final signed download URL
3. Falls back to the dl link if redirect resolution fails

Example: `python3 sonos.py play-dropbox https://www.dropbox.com/scl/fi/abc123/song.mp3`

### Transport Controls
```bash
python3 sonos.py pause [player_ip]
python3 sonos.py stop [player_ip]
python3 sonos.py next [player_ip]
python3 sonos.py prev [player_ip]
python3 sonos.py seek <seconds> [player_ip]
```

### Volume
```bash
python3 sonos.py volume <0-100> [player_ip]
python3 sonos.py volume-up [player_ip]
python3 sonos.py volume-down [player_ip]
python3 sonos.py mute [player_ip]
python3 sonos.py unmute [player_ip]
```

### EQ
```bash
python3 sonos.py set-bass <level> [player_ip]  # -15 to +15
python3 sonos.py set-treble <level> [player_ip]  # -15 to +15
python3 sonos.py EQ <bass> <treble> [player_ip]
```

### Grouping
```bash
python3 sonos.py group <coordinator_ip> [member_ip, ...]
python3 sonos.py ungroup [player_ip]
```

## How It Works

Uses the **soco** Python library which communicates with Sonos devices via UPnP/DLNA SOAP protocol on port 1400.

## Common Use Cases

**"What's playing?"** → `sonos.py state`
**"Turn it up"** → `sonos.py volume-up`
**"Play Spotify"** → `sonos.py play-spotify spotify:track:track-id`
**"Play radio"** → `sonos.py play-radio http://stream-url`
**"Play Dropbox"** → `sonos.py play-dropbox https://www.dropbox.com/scl/fi/...`
