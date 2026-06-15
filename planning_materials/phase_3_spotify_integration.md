# Phase Spotify 3: Full Playback — Sonos, Browser SDK & Controls Integration

## What This Phase Builds
- Sonos Spotify playback: new endpoint converts `spotify:track:xxx` URIs to Sonos-native format and plays them via soco
- Spotify Web Playback SDK for in-browser Spotify audio (requires Spotify Premium; graceful fallback for non-Premium)
- `window.spotifyPlay()` — the function Phase 2's play buttons already call
- Extends Phase 4's `onPrev`, `onNext`, `onPlayPause` to handle two new playback modes: `spotify-browser` and `spotify-sonos`
- Spotify state polling (now-playing title/artist updates in the controls bar)
- Full end-to-end: search → browse → pin → play on Sonos or browser → visualizer expand works as-is

---

## Full App Context
You are completing the Spotify integration in **SonosWeb**.

**Already built across previous phases:**

| Phase | What's available |
|-------|-----------------|
| Phase 4 (core app) | `playback` object, `updateNowPlaying(title, mode)`, `setPlayPauseBtn(bool)`, `onPrev()`, `onNext()`, `onPlayPause()`, `startSonosPoller()`, `stopSonosPoller()`. Playback modes: `'browser'` and `'sonos'`. |
| Phase 5 (visualizer) | `openExpandedPlayer()`, `closeExpandedPlayer()`. Visualizer uses mic — works unchanged for Spotify. |
| Spotify Phase 1 | `GET /api/spotify/token` returns current access token. `POST /api/spotify/player/play-track`, `/player/pause`, `/player/resume`, `/player/next`, `/player/previous`, `GET /api/spotify/player/state` all exist. |
| Spotify Phase 2 | `window.spotifyPlay(mode, context, id, uri, name)` is called by all play buttons in the Spotify tab. Currently a stub (`console.log`). This phase defines it for real. |
| Core app `routers/sonos.py` | Has `play_uri()` via `sc.play_uri(sonos_ip, uri, title)` and `play_queue()` via `sc.play_queue(sonos_ip, uris, titles)`. These are used for mp3 playback. Phase 3 adds Spotify-specific wrappers. |

**Two new playback modes added by this phase:**
- `'spotify-browser'` — audio via Spotify Web Playback SDK in the browser
- `'spotify-sonos'` — audio via Sonos native Spotify integration (x-sonos-spotify: URIs)

The controls bar handles all four modes transparently. The spectrum visualizer (mic-based) already works for all modes unchanged.

---

## Files to Modify

```
sonosweb/
├── routers/
│   └── sonos.py          ← MODIFY (add Spotify-on-Sonos endpoints)
├── templates/
│   └── index.html        ← MODIFY (add Spotify Web Playback SDK script tag)
└── static/
    └── app.js            ← MODIFY (append Spotify playback engine + controls integration)
```

---

## Implementation

### Modify `routers/sonos.py` — add Spotify-on-Sonos endpoints

The Sonos speaker plays Spotify tracks via its native UPnP Spotify integration. The URI format is `x-sonos-spotify:spotify%3atrack%3a{track_id}`. This requires the Sonos speaker to have a Spotify account linked in the Sonos app (standard for most users). The conversion is already in the original `sonos.py` script the app was built from.

Append to `routers/sonos.py`:

```python
# ── Spotify-on-Sonos playback ─────────────────────────────────

def _spotify_uri_to_sonos(spotify_track_uri: str) -> str:
    """
    Convert spotify:track:TRACK_ID → x-sonos-spotify:spotify%3atrack%3aTRACK_ID
    This is the URI format Sonos uses to play Spotify tracks natively.
    The Sonos speaker must have Spotify linked in the Sonos app.
    """
    track_id = spotify_track_uri.split(":")[-1]
    return f"x-sonos-spotify:spotify%3atrack%3a{track_id}"


class PlaySpotifyTrackOnSonosRequest(BaseModel):
    spotify_uri: str       # e.g. spotify:track:abc123
    name:        str = ""


class PlaySpotifyAlbumOnSonosRequest(BaseModel):
    track_uris:  list[str]  # ordered list of spotify:track:xxx URIs
    names:       list[str]  # matching track names for display
    album_name:  str = ""


@router.post("/play-spotify-track")
async def play_spotify_track_on_sonos(req: PlaySpotifyTrackOnSonosRequest):
    """Play a single Spotify track on Sonos using native Spotify integration."""
    sonos_ip  = _get_sonos_ip()
    sonos_uri = _spotify_uri_to_sonos(req.spotify_uri)
    loop      = asyncio.get_event_loop()
    result    = await loop.run_in_executor(None, sc.play_uri, sonos_ip, sonos_uri, req.name)
    return {**result, "spotify_uri": req.spotify_uri, "sonos_uri": sonos_uri, "title": req.name}


@router.post("/play-spotify-album")
async def play_spotify_album_on_sonos(req: PlaySpotifyAlbumOnSonosRequest):
    """
    Load all tracks of a Spotify album into the Sonos queue and start playing.
    track_uris: list of spotify:track:xxx in play order.
    """
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
```

> **Note on `play_queue` with Spotify URIs:** `sc.play_queue` calls `player.add_uri_to_queue(uri)` for each URI, then `player.play_from_queue(0)`. If your Sonos model rejects x-sonos-spotify URIs in the queue (raises `SoCoUPnPException` with error 701), fall back to playing just the first track via `play_uri` and rely on Sonos's own queue. Log the error and return the first-track fallback. Most Sonos models (Beam, Arc, Era) accept these URIs correctly.

---

### Modify `templates/index.html` — add Spotify SDK

Add the Spotify Web Playback SDK `<script>` tag. Place it **before** `<script src="/static/app.js">`:

```html
<!-- Spotify Web Playback SDK (loaded async, initialized in app.js only when needed) -->
<script src="https://sdk.scdn.co/spotify-player.js" async></script>
```

The SDK calls `window.onSpotifyWebPlaybackSDKReady()` when it loads. Our JS defines this hook and stores the `Spotify` global for later use.

---

### `static/app.js` — append Spotify playback engine

Append the entire block below to the end of `app.js`. It:
1. Sets up the Spotify Web Playback SDK
2. Defines `window.spotifyPlay()` (called by Phase 2 play buttons)
3. Extends Phase 4's `onPrev` / `onNext` / `onPlayPause` to handle the two new Spotify modes
4. Adds Spotify state polling

```javascript
/* ============================================================
   SPOTIFY — Phase 3: Full Playback Engine
   ============================================================ */

// ── Spotify Web Playback SDK state ───────────────────────────
const spotifySdk = {
    player:    null,      // Spotify.Player instance
    deviceId:  null,      // assigned device_id from SDK ready event
    ready:     false,     // true once SDK player is connected
    initAttempted: false, // avoid re-initing if SDK fails
};

// SDK ready hook (called by spotify-player.js when it loads)
window.onSpotifyWebPlaybackSDKReady = () => {
    console.log('[Spotify SDK] Ready');
    // Don't init the player until first browser-mode play attempt
    // (avoids permission prompts before user interacts)
    spotifySdk.sdkLoaded = true;
};

async function initSpotifySdkPlayer() {
    if (spotifySdk.initAttempted) return;
    spotifySdk.initAttempted = true;

    if (!window.Spotify) {
        console.warn('[Spotify SDK] SDK not loaded yet');
        return;
    }

    // Get current access token from backend
    let token;
    try {
        const res = await fetch('/api/spotify/token');
        const data = await res.json();
        token = data.access_token;
    } catch (e) {
        console.error('[Spotify SDK] Failed to get token:', e);
        return;
    }
    if (!token) return;

    spotifySdk.player = new window.Spotify.Player({
        name: 'SonosWeb',
        getOAuthToken: async (cb) => {
            // Called by SDK when token needs refreshing
            const r    = await fetch('/api/spotify/token');
            const data = await r.json();
            cb(data.access_token || token);
        },
        volume: 0.8,
    });

    // SDK event listeners
    spotifySdk.player.addListener('ready', ({ device_id }) => {
        console.log('[Spotify SDK] Player ready, device_id:', device_id);
        spotifySdk.deviceId = device_id;
        spotifySdk.ready    = true;
    });

    spotifySdk.player.addListener('not_ready', ({ device_id }) => {
        console.warn('[Spotify SDK] Device not ready:', device_id);
        spotifySdk.ready = false;
    });

    spotifySdk.player.addListener('player_state_changed', (state) => {
        if (!state) return;
        const track    = state.track_window?.current_track;
        const isPaused = state.paused;
        if (track && playback.mode === 'spotify-browser') {
            const title = `${track.name} — ${track.artists?.map(a=>a.name).join(', ')}`;
            updateNowPlaying(title, 'spotify-browser');
            setPlayPauseBtn(!isPaused);
        }
    });

    spotifySdk.player.addListener('initialization_error', ({ message }) => {
        console.error('[Spotify SDK] Init error:', message);
    });
    spotifySdk.player.addListener('authentication_error', ({ message }) => {
        console.error('[Spotify SDK] Auth error:', message);
        showToast('Spotify auth error — try reconnecting in Settings', 'error');
    });
    spotifySdk.player.addListener('account_error', ({ message }) => {
        // Non-Premium account
        console.warn('[Spotify SDK] Account error (likely non-Premium):', message);
        spotifySdk.ready = false;
        showToast('Spotify browser playback requires Premium. Use ▶ Sonos instead.', 'error');
    });

    const connected = await spotifySdk.player.connect();
    if (!connected) {
        console.warn('[Spotify SDK] Player failed to connect');
        spotifySdk.initAttempted = false;  // allow retry
    }
}

// ── Main Spotify play dispatcher ─────────────────────────────
// Called by Phase 2's play buttons via: window.spotifyPlay(mode, context, id, uri, name)

window.spotifyPlay = async function(mode, context, id, uri, name) {
    if (mode === 'browser') {
        await spotifyPlayBrowser(context, id, uri, name);
    } else {
        await spotifyPlaySonos(context, id, uri, name);
    }
};

// ── Play on Sonos ─────────────────────────────────────────────

async function spotifyPlaySonos(context, id, uri, name) {
    // Stop any in-browser audio
    if (typeof audioEl !== 'undefined' && audioEl) {
        audioEl.pause();
        audioEl.src = '';
    }
    if (typeof spotifySdk.player !== 'undefined' && spotifySdk.player && playback.mode === 'spotify-browser') {
        spotifySdk.player.pause();
    }
    stopSonosPoller();

    if (context === 'track') {
        const spotifyUri = uri || `spotify:track:${id}`;
        try {
            const res  = await fetch('/api/sonos/play-spotify-track', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ spotify_uri: spotifyUri, name: name || id }),
            });
            const data = await res.json();
            if (data.status === 'error') {
                showToast('Sonos Spotify error: ' + data.message, 'error');
                return;
            }
            playback.isPaused = false;
            updateNowPlaying(name || id, 'spotify-sonos');
            setPlayPauseBtn(true);
            startSpotifySonosPoller();
            showToast(`Playing on Sonos: ${name}`, 'success');
        } catch (err) {
            showToast('Sonos Spotify play failed: ' + err.message, 'error');
        }

    } else if (context === 'album') {
        // Fetch tracks for the album then queue on Sonos
        showToast('Loading album into Sonos queue…', 'success');
        try {
            // Try pinned tracks first; fall back to live Spotify API
            let tracks = [];
            const pinnedRes = await fetch(`/api/spotify/pins/tracks/${encodeURIComponent(id)}`);
            const pinnedData = await pinnedRes.json();
            tracks = pinnedData.tracks || [];

            if (!tracks.length) {
                const liveRes  = await fetch(`/api/spotify/album/${encodeURIComponent(id)}/tracks`);
                const liveData = await liveRes.json();
                tracks = (liveData.tracks || []).map(t => ({ ...t, spotify_id: t.id }));
            }

            const trackUris = tracks.map(t => `spotify:track:${t.spotify_id || t.id}`);
            const names     = tracks.map(t => t.name);
            const res  = await fetch('/api/sonos/play-spotify-album', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ track_uris: trackUris, names, album_name: name }),
            });
            const data = await res.json();
            if (data.status === 'error') {
                showToast('Sonos queue error: ' + data.message, 'error');
                return;
            }
            playback.isPaused = false;
            updateNowPlaying(data.first_title || name, 'spotify-sonos');
            setPlayPauseBtn(true);
            startSpotifySonosPoller();
            showToast(`${data.track_count} tracks queued on Sonos`, 'success');
        } catch (err) {
            showToast('Failed to queue album: ' + err.message, 'error');
        }

    } else if (context === 'artist') {
        // Queue all pinned tracks for this artist
        showToast('Loading artist tracks into Sonos queue…', 'success');
        try {
            // Get pinned albums for artist, then collect all pinned tracks
            const albumsRes  = await fetch(`/api/spotify/pins/albums/${encodeURIComponent(id)}`);
            const albumsData = await albumsRes.json();
            const albums = albumsData.albums || [];
            const allTracks = [];
            for (const al of albums) {
                const tracksRes  = await fetch(`/api/spotify/pins/tracks/${encodeURIComponent(al.spotify_id)}`);
                const tracksData = await tracksRes.json();
                allTracks.push(...(tracksData.tracks || []));
            }
            if (!allTracks.length) {
                showToast('No pinned tracks for this artist. Pin some albums first.', 'error');
                return;
            }
            const trackUris = allTracks.map(t => `spotify:track:${t.spotify_id}`);
            const names     = allTracks.map(t => t.name);
            const res = await fetch('/api/sonos/play-spotify-album', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ track_uris: trackUris, names, album_name: name }),
            });
            const data = await res.json();
            playback.isPaused = false;
            updateNowPlaying(data.first_title || name, 'spotify-sonos');
            setPlayPauseBtn(true);
            startSpotifySonosPoller();
            showToast(`${data.track_count} tracks queued on Sonos`, 'success');
        } catch (err) {
            showToast('Failed to queue artist: ' + err.message, 'error');
        }

    } else if (context === 'playlist') {
        // Load playlist tracks then queue
        showToast('Loading playlist into Sonos queue…', 'success');
        try {
            const res    = await fetch(`/api/spotify/playlist/${encodeURIComponent(id)}/tracks`);
            const data   = await res.json();
            const tracks = data.tracks || [];
            if (!tracks.length) { showToast('Playlist is empty', 'error'); return; }
            const trackUris = tracks.map(t => `spotify:track:${t.id}`);
            const names     = tracks.map(t => t.name);
            const qRes = await fetch('/api/sonos/play-spotify-album', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ track_uris: trackUris, names, album_name: name }),
            });
            const qData = await qRes.json();
            playback.isPaused = false;
            updateNowPlaying(qData.first_title || name, 'spotify-sonos');
            setPlayPauseBtn(true);
            startSpotifySonosPoller();
            showToast(`${qData.track_count} tracks queued on Sonos`, 'success');
        } catch (err) {
            showToast('Failed to queue playlist: ' + err.message, 'error');
        }
    }
}

// ── Play in browser (Spotify Web Playback SDK) ────────────────

async function spotifyPlayBrowser(context, id, uri, name) {
    // Initialize SDK if not yet done
    if (!spotifySdk.ready) {
        await initSpotifySdkPlayer();
        // Wait briefly for SDK to connect
        await new Promise(resolve => setTimeout(resolve, 1500));
    }

    if (!spotifySdk.ready || !spotifySdk.deviceId) {
        showToast('Spotify browser playback unavailable. Premium required. Try ▶ Sonos instead.', 'error');
        return;
    }

    // Stop any other audio
    if (typeof audioEl !== 'undefined' && audioEl) { audioEl.pause(); audioEl.src = ''; }
    stopSonosPoller();

    let uris = [];
    let displayName = name || id;

    if (context === 'track') {
        uris = [uri || `spotify:track:${id}`];
    } else if (context === 'album') {
        // Get track URIs for album
        const pinnedRes  = await fetch(`/api/spotify/pins/tracks/${encodeURIComponent(id)}`);
        const pinnedData = await pinnedRes.json();
        let tracks = pinnedData.tracks || [];
        if (!tracks.length) {
            const liveRes  = await fetch(`/api/spotify/album/${encodeURIComponent(id)}/tracks`);
            const liveData = await liveRes.json();
            tracks = liveData.tracks || [];
        }
        uris = tracks.map(t => `spotify:track:${t.spotify_id || t.id}`);
        displayName = tracks[0]?.name ? `${tracks[0].name} (${name})` : name;
    } else if (context === 'artist') {
        // First pinned track for the artist
        const albumsRes  = await fetch(`/api/spotify/pins/albums/${encodeURIComponent(id)}`);
        const albumsData = await albumsRes.json();
        const firstAlbum = (albumsData.albums || [])[0];
        if (firstAlbum) {
            const tracksRes  = await fetch(`/api/spotify/pins/tracks/${encodeURIComponent(firstAlbum.spotify_id)}`);
            const tracksData = await tracksRes.json();
            uris = (tracksData.tracks || []).map(t => `spotify:track:${t.spotify_id}`);
        }
    } else if (context === 'playlist') {
        const res  = await fetch(`/api/spotify/playlist/${encodeURIComponent(id)}/tracks`);
        const data = await res.json();
        uris = (data.tracks || []).map(t => `spotify:track:${t.id}`);
    }

    if (!uris.length) {
        showToast('No tracks to play', 'error');
        return;
    }

    try {
        const res  = await fetch('/api/spotify/player/play-tracks', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ uris, device_id: spotifySdk.deviceId }),
        });
        const data = await res.json();
        if (data.error) {
            showToast('Spotify play error: ' + data.error, 'error');
            return;
        }
        playback.isPaused = false;
        updateNowPlaying(displayName, 'spotify-browser');
        setPlayPauseBtn(true);
        // SDK state_changed events update the title automatically
        showToast(`Playing in browser: ${displayName}`, 'success');
    } catch (err) {
        showToast('Spotify browser play failed: ' + err.message, 'error');
    }
}

// ── Extend Phase 4 controls bar handlers ─────────────────────
// Phase 4 defines onPrev, onNext, onPlayPause as `function` declarations.
// We override them here (last declaration wins for function statements in same scope).
// If Phase 4 uses `const` or arrow functions, adjust accordingly — see note below.

const _p4_onPlayPause = typeof onPlayPause === 'function' ? onPlayPause : () => {};
const _p4_onNext      = typeof onNext      === 'function' ? onNext      : () => {};
const _p4_onPrev      = typeof onPrev      === 'function' ? onPrev      : () => {};

function onPlayPause() {
    if (playback.mode === 'spotify-browser') {
        if (!spotifySdk.player) return;
        spotifySdk.player.togglePlay();
    } else if (playback.mode === 'spotify-sonos') {
        if (playback.isPaused) {
            fetch('/api/spotify/player/resume', { method: 'POST' });
            // Also resume via Sonos soco (belt-and-suspenders)
            fetch('/api/sonos/resume', { method: 'POST' });
            playback.isPaused = false;
            setPlayPauseBtn(true);
        } else {
            fetch('/api/spotify/player/pause', { method: 'POST' });
            fetch('/api/sonos/pause', { method: 'POST' });
            playback.isPaused = true;
            setPlayPauseBtn(false);
        }
    } else {
        _p4_onPlayPause();
    }
}

function onNext() {
    if (playback.mode === 'spotify-browser') {
        spotifySdk.player?.nextTrack();
    } else if (playback.mode === 'spotify-sonos') {
        // For Sonos queue mode: use soco next
        fetch('/api/sonos/next', { method: 'POST' })
            .then(() => setTimeout(syncSpotifySonosState, 600));
    } else {
        _p4_onNext();
    }
}

function onPrev() {
    if (playback.mode === 'spotify-browser') {
        spotifySdk.player?.previousTrack();
    } else if (playback.mode === 'spotify-sonos') {
        fetch('/api/sonos/previous', { method: 'POST' })
            .then(() => setTimeout(syncSpotifySonosState, 600));
    } else {
        _p4_onPrev();
    }
}

// ── Spotify-on-Sonos state polling ───────────────────────────
// Polls Sonos transport state to keep "Now Playing" label up to date
// as the queue advances (same mechanism as the mp3 Sonos poller in Phase 4).

let _spotifySonosPoller = null;

function startSpotifySonosPoller() {
    if (_spotifySonosPoller) clearInterval(_spotifySonosPoller);
    syncSpotifySonosState();
    _spotifySoller = setInterval(syncSpotifySonosState, 3000);
    _spotifySonosPoller = _spotifySoller;
}

function stopSpotifySonosPoller() {
    if (_spotifySonosPoller) { clearInterval(_spotifySonosPoller); _spotifySonosPoller = null; }
}

async function syncSpotifySonosState() {
    if (playback.mode !== 'spotify-sonos') { stopSpotifySonosPoller(); return; }
    try {
        // Use Sonos state (which reflects what's actually playing on the speaker)
        const res  = await fetch('/api/sonos/state');
        const data = await res.json();
        const title = data.title || playback.currentTitle;
        if (title && title !== playback.currentTitle) {
            updateNowPlaying(title, 'spotify-sonos');
        }
        const isPlaying = data.state === 'PLAYING';
        playback.isPaused = (data.state === 'PAUSED_PLAYBACK');
        setPlayPauseBtn(isPlaying);
        if (data.state === 'STOPPED' || data.state === 'NO_MEDIA_PRESENT') {
            stopSpotifySonosPoller();
        }
    } catch (err) {
        // Transient Sonos network issue — keep polling
    }
}

// ── Sync expanded player play/pause icon for Spotify modes ───
// Phase 5's setPlayPauseBtn patch already calls syncEpPlayPauseIcon(),
// so the expanded player icon updates automatically for all modes.

// ── Mode badge display for Spotify modes ─────────────────────
// Phase 4's updateNowPlaying sets the compact bar mode badge.
// We extend the badge text for Spotify modes:
(function patchSpotifyModeBadge() {
    const _origUpdate = typeof updateNowPlaying === 'function' ? updateNowPlaying : () => {};
    // Already patched by Phase 5? Merge safely.
    const _alreadyPatched = window._patchedUpdateNowPlaying;

    const newPatch = function(title, mode) {
        // Call the chain: original → Phase5 patch → here
        (_alreadyPatched || _origUpdate)(title, mode);

        // Override mode badge text for Spotify-specific modes
        const badge = document.getElementById('now-playing-mode');
        if (badge) {
            if (mode === 'spotify-browser') {
                badge.textContent = 'Spotify';
                badge.className   = 'mode-badge spotify-browser-badge';
            } else if (mode === 'spotify-sonos') {
                badge.textContent = 'Spotify → Sonos';
                badge.className   = 'mode-badge spotify-sonos-badge';
            }
        }

        // Same for expanded player badge
        const epBadge = document.getElementById('ep-mode-badge');
        if (epBadge) {
            if (mode === 'spotify-browser') {
                epBadge.textContent = 'Spotify';
                epBadge.className   = 'ep-mode-badge spotify-browser-badge';
            } else if (mode === 'spotify-sonos') {
                epBadge.textContent = 'Spotify → Sonos';
                epBadge.className   = 'ep-mode-badge spotify-sonos-badge';
            }
        }
    };
    window._patchedUpdateNowPlaying = newPatch;
})();
```

---

### CSS additions to `static/style.css`

Append:

```css
/* ============================================================
   SPOTIFY — Phase 3: Mode badges for Spotify playback modes
   ============================================================ */

.mode-badge.spotify-browser-badge,
.ep-mode-badge.spotify-browser-badge {
  background: rgba(29,185,84,0.2);
  color: #1db954;
}

.mode-badge.spotify-sonos-badge,
.ep-mode-badge.spotify-sonos-badge {
  background: rgba(29,185,84,0.12);
  color: #1db954;
  font-size: 0.65rem;   /* slightly smaller for the longer text */
}
```

---

## New API Endpoints (Phase 3)

| Method | Path | Body | Description |
|--------|------|------|-------------|
| `POST` | `/api/sonos/play-spotify-track` | `{spotify_uri, name}` | Play one Spotify track on Sonos via native x-sonos-spotify: |
| `POST` | `/api/sonos/play-spotify-album` | `{track_uris[], names[], album_name}` | Queue Spotify album/playlist on Sonos |

(Spotify browser playback uses existing `/api/spotify/player/*` endpoints from Phase 1.)

---

## Validation Steps

### 1. Sonos — single track
- Ensure your Sonos speaker has Spotify logged in (standard Sonos app setup).
- Browse to any track in the Spotify tab, click "▶ Sonos".
- Toast: "Playing on Sonos: Track Name".
- Controls bar appears with "Spotify → Sonos" badge.
- Track should start playing on the Sonos speaker.

### 2. Sonos — album queue
- Click "▶ Sonos" on an album row.
- Toast: "Loading album into Sonos queue…" then "N tracks queued on Sonos".
- Controls bar shows first track name.
- ⏭ next button advances the Sonos queue through the album.

### 3. Sonos — artist queue (all pinned tracks)
- Click "▶ Sonos" on an artist row.
- All pinned tracks for the artist are queued on Sonos in album order.

### 4. Sonos state polling
- While Sonos plays an album queue, wait for first track to end.
- "Now Playing" label in controls bar updates to the next track title within ~3 seconds.

### 5. Browser — single track (Spotify Premium)
- Click "▶ Browser" on a track.
- If first time: SDK initializes (may take 1–2 seconds).
- Track plays in the browser tab (audio from SonosWeb device in Spotify Connect).
- Controls bar shows "Spotify" badge.
- Pause/resume works via the controls bar.

### 6. Browser — non-Premium fallback
- Log in with a non-Premium Spotify account.
- Click "▶ Browser" on any track.
- Toast: "Spotify browser playback requires Premium. Use ▶ Sonos instead."
- No audio plays. ▶ Sonos still works.

### 7. Controls bar — all modes
- Play a track in browser mp3 mode. Pause. Switch to Spotify browser mode. Pause. Switch to Spotify Sonos. Pause. Verify each mode's pause/resume routes to the correct handler (browser audio el / SDK / Sonos API).

### 8. Visualizer — expand works unchanged
- While any Spotify mode is playing, click ⛶ expand.
- Expanded player slides up, mic permission requested (if first time).
- Spectrum visualizer picks up room audio (Sonos speaker / laptop speakers).
- Track name and "Spotify → Sonos" or "Spotify" badge shown in expanded view.
- ⏸ in expanded view pauses the Spotify playback correctly.

### 9. Play buttons via search results
- Search "all Spotify" for an artist, click "▶ Sonos" directly from search results.
- (Phase 2 buttons call `window.spotifyPlay('sonos', 'artist', id, null, name)` — now wired.)
- If artist has pinned tracks: queues them. If not: shows message to pin first.

### 10. Sonos API test
```bash
curl -X POST http://localhost:8000/api/sonos/play-spotify-track \
  -H "Content-Type: application/json" \
  -d '{"spotify_uri": "spotify:track:2TpxZ7JUBn3uw46aR7qd6V", "name": "Teardrop"}'
# → {"status": "playing", "sonos_uri": "x-sonos-spotify:spotify%3atrack%3a2TpxZ7JUBn3uw46aR7qd6V", ...}
```

---

## Notes & Gotchas

### Function override strategy
Phase 4 declares `onPlayPause`, `onNext`, `onPrev` as `function` statements. In JS, `function` declarations are hoisted but the **last** one in the file wins at runtime. Since Phase 3's JS is appended after Phase 4's in `app.js`, the Phase 3 overrides take effect. However, if Phase 4 used `const onPlayPause = ...` (arrow/const), you cannot re-declare in the same scope. In that case, replace the override approach with direct patching inside the existing functions by checking `playback.mode` — or restructure Phase 4 to use a dispatching pattern.

### Spotify Web Playback SDK device timing
After `player.connect()`, there is a delay (typically 500–1500ms) before `device_id` is assigned via the `ready` event. `spotifyPlayBrowser` waits 1500ms after calling `initSpotifySdkPlayer()`. If the device is still not ready after that wait, the play attempt will fail with a toast message. The user can try again immediately — subsequent attempts skip the init delay.

### Sonos Spotify integration prerequisite
The Sonos speaker must have a Spotify account linked via the Sonos app (Settings → Music & Content → Add Music Services → Spotify). Without this, x-sonos-spotify: URIs will be rejected with a Sonos UPnP error. This is a one-time user setup, not an app concern.

### `play_queue` with x-sonos-spotify: URIs
The soco `player.add_uri_to_queue('x-sonos-spotify:...')` works on most Sonos models. Some older models or firmware versions may reject these. If you see `SoCoUPnPException: UPnP Error 701 incompatible` in the server logs, implement the fallback: play only the first track via `play_uri()` and log the queue failure. The user can use Sonos's own "Up Next" for subsequent tracks.

### Sonos queue vs Spotify API queue
When playing Spotify on Sonos via x-sonos-spotify: URIs, prev/next use Sonos's queue (via soco `next()`/`previous()`), not Spotify's queue. This means Spotify's own "next track" logic is bypassed. This is intentional and matches how the mp3 queue works. Sonos handles the track order correctly.

### Spotify browser + Sonos at the same time
The `window.spotifyPlay` dispatcher always stops the other mode before starting. Playing "Browser" stops any Sonos audio (pauses via soco). Playing "Sonos" pauses the SDK player. This prevents both playing simultaneously. Note: pausing via soco affects the Sonos speaker's entire Spotify queue — if the user has music playing from the Sonos app itself, it will be interrupted.

### Polling strategy summary
| Mode | Poller | Update source |
|------|--------|---------------|
| `browser` (mp3) | Phase 4 `startSonosPoller()` | Sonos transport state |
| `sonos` (mp3) | Phase 4 `startSonosPoller()` | Sonos transport state |
| `spotify-browser` | SDK `player_state_changed` event | Spotify SDK (push, no polling) |
| `spotify-sonos` | `startSpotifySonosPoller()` | Sonos transport state (3s interval) |

The SDK's `player_state_changed` event fires automatically when the track changes in browser mode, so no interval polling is needed — the title updates automatically.
