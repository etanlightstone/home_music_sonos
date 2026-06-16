# SonosWeb

A web-based Sonos music controller that lets you browse, search, and play local music files on your Sonos speakers. Music is indexed from an FTP/SFTP server on your LAN, and the web UI provides playback controls, search with metadata support, and a file browser with folder navigation.

![Music Player Screenshot](static/music_player.jpeg)

## Features

- **Music Browser** — Navigate remote music libraries via FTP/SFTP with breadcrumb folder navigation
- **Search** — Multi-facet search across file names, folder names, and ID3 metadata
- **Sonos Playback** — Play individual tracks or entire folders on your Sonos speakers
- **Playback Controls** — Persistent now-playing bar with play/pause, next/previous, and current track info
- **Settings** — Configure Sonos speaker IP, FTP/SFTP credentials, and trigger re-indexing
- **Background Indexing** — Recursively indexes remote music files into a local SQLite DB with progress indication
- **Spotify** — OAuth login, search, pinned library (artists/albums/tracks), and playback via Sonos or browser

## Quick Start

```bash
git clone https://github.com/your-username/sonosweb.git
cd sonosweb
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Or use the provided startup script:

```bash
bash app.sh
```

This starts two instances — HTTP on port 8000 (for Sonos playback URLs) and HTTPS on port 443 (for the web UI with the audio visualizer). The HTTPS instance is optional — it's only needed if you want microphone access in the browser for the audio visualizer, since modern browsers block `getUserMedia()` on insecure origins.

## Docker

```bash
docker build -t sonosweb .
docker run -p 8000:8000 -p 443:443 sonosweb
```

> **Note:** The Dockerfile is currently outdated for LAN use. Running directly on the host is recommended when using dual HTTP/HTTPS ports.

## Spotify Integration

Browse, search, pin, and play Spotify music through both Sonos (via native `x-sonos-spotify:` URIs) and in-browser (via the Spotify Web Playback SDK, requires Premium).

### Setup

Spotify credentials are **not** included in the repo — you must register your own app.

1. Create your own app on the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Add a **Redirect URI** in the Spotify Dashboard — must be either:
   - `http://localhost:8000/spotify/callback` (if browsing on the same machine)
   - `https://<your-lan-ip>/spotify/callback` (if accessing from another device)
   - **HTTPS is required** for non-`localhost` redirect URIs — Spotify's OAuth will reject plain HTTP for IP-based redirects.
3. Copy your app's **Client ID** and **Client Secret** from the Dashboard.
4. Open Settings in SonosWeb → **Spotify** section → paste Client ID, Client Secret, and the matching Redirect URI.
5. Click **Connect Spotify Account** and authorize through Spotify's OAuth page.

The redirect URI in Settings must match the one registered in the Spotify Developer Dashboard **exactly** (trailing slashes, protocol, port — everything).

> **Note:** The Sonos speaker must have Spotify linked in the Sonos app (Settings → Music & Content → Add Music Services → Spotify) for Sonos playback to work.

## Tech Stack

- **Backend:** Python, FastAPI, Jinja2
- **Frontend:** Vanilla JavaScript, CSS (dark theme)
- **Sonos:** soco library
- **Spotify:** spotipy, Spotify Web Playback SDK
- **Database:** SQLite via aiosqlite
- **File Transfer:** paramiko (SFTP), ftplib (FTP)
