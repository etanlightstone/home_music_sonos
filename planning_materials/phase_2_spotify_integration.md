# Phase Spotify 2: Pinned Library Browser — Hierarchy UI & Pin System

## What This Phase Builds
- Pin/unpin API endpoints (pin a track, album, or artist; unpin any item)
- Pinned library query endpoints (artists list, albums for artist, tracks for album)
- Full Spotify browser UI inside the `#spotify-browser` div — Artist → Album → Track hierarchy that mirrors the mp3 browser's look and feel exactly
- Playlist browsing mode (toggle between Artists and Playlists within the Spotify tab)
- "Live from Spotify" album browsing for artist-type pins (no tracks pinned yet)
- Pin/Unpin buttons on every row
- Empty state when nothing is pinned
- Breadcrumb navigation within the Spotify browser

**No playback wiring yet** — the ▶ Sonos and ▶ Browser buttons render but call stubs (Phase 3 wires them up). Pin/unpin is fully functional.

---

## Full App Context
You are extending **SonosWeb**. Phase Spotify 1 already built:
- `services/spotify_client.py` — all Spotify API calls (`get_artist_albums`, `get_album_tracks`, `get_user_playlists`, `get_playlist_tracks`, etc.)
- `routers/spotify.py` — OAuth, metadata endpoints (`/api/spotify/artist/{id}/albums`, `/api/spotify/album/{id}/tracks`, etc.), auth-status
- `database.py` `spotify_pins` table with columns: `id, item_type, spotify_id, name, artist_id, artist_name, album_id, album_name, track_number, disc_number, duration_ms, image_url, pinned_at`
- `templates/index.html` — Spotify tab with `#spotify-auth-prompt` (shown when not authed) and `#spotify-browser` div (shown when authed, currently just a placeholder `<p>`)
- `static/app.js` — `checkSpotifyAuth()`, `switchTab()`, `showToast()`, `escHtml()`, `formatBytes()`, `formatDate()` all available

**The mp3 browser** uses these CSS classes that Spotify rows should reuse: `.file-row`, `.folder-row`, `.file-row-music`, `.file-icon`, `.file-name`, `.file-meta`, `.file-actions`, `.btn-primary`, `.btn-secondary`, `.breadcrumb`, `.file-list`, `.empty-state`, `.loading-row`.

---

## Files to Modify

```
sonosweb/
├── routers/
│   └── spotify.py          ← MODIFY (add pin/unpin + pinned library query endpoints)
├── templates/
│   └── index.html          ← MODIFY (replace placeholder in #spotify-browser)
├── static/
│   ├── style.css           ← MODIFY (append Spotify-specific styles)
│   └── app.js              ← MODIFY (append full Spotify browser JS)
```

---

## Pin Data Model Reference

How the hierarchy is constructed from `spotify_pins`:

| Scenario | What's in DB | What user sees in pinned view |
|----------|-------------|-------------------------------|
| Pin a track | 1 row: `type=track, artist_id=X, album_id=Y` | Artist X → Album Y → that track |
| Pin an album | 1 artist row + N track rows (all album tracks inserted) | Artist → Album → all tracks |
| Pin an artist | 1 row: `type=artist, spotify_id=X` | Artist X (albums fetched live from Spotify API when drilled into) |
| Pin artist then pin their album | artist row + N track rows | Artist → Album (with all tracks) |
| Pin one track, then pin its album | track row merged into N track rows | Artist → Album → all tracks |

**Pinned Artists view query** — UNION of artist-type pins and distinct artist_ids from track/album pins:
```sql
SELECT spotify_id, name, image_url FROM spotify_pins WHERE item_type='artist'
UNION
SELECT DISTINCT artist_id AS spotify_id, artist_name AS name, image_url
  FROM spotify_pins WHERE item_type IN ('album','track') AND artist_id IS NOT NULL
ORDER BY name COLLATE NOCASE
```

**Pinned Albums for artist query**:
```sql
SELECT DISTINCT album_id AS spotify_id, album_name AS name, image_url
  FROM spotify_pins WHERE artist_id=? AND album_id IS NOT NULL
ORDER BY name COLLATE NOCASE
```

**Pinned Tracks for album query**:
```sql
SELECT * FROM spotify_pins
  WHERE album_id=? AND item_type='track'
  ORDER BY disc_number, track_number
```

**Is item pinned?** `SELECT id FROM spotify_pins WHERE spotify_id=? LIMIT 1`

---

## Implementation

### Add to `routers/spotify.py`

Append these endpoints to the existing `routers/spotify.py`:

```python
# ── Pin/Unpin endpoints ──────────────────────────────────────

class PinRequest(BaseModel):
    item_type:   str            # 'artist' | 'album' | 'track'
    spotify_id:  str
    name:        str
    artist_id:   Optional[str] = None
    artist_name: Optional[str] = None
    album_id:    Optional[str] = None
    album_name:  Optional[str] = None
    track_number: Optional[int] = None
    disc_number:  Optional[int] = 1
    duration_ms:  Optional[int] = None
    image_url:    Optional[str] = None


@router.post("/pin")
async def pin_item(req: PinRequest):
    """
    Pin a Spotify item. Pinning an album also fetches and pins all its tracks.
    Pinning an artist adds just the artist row (albums browsed live from Spotify).
    """
    from database import get_db
    conn = get_db()

    if req.item_type == "album":
        # Fetch all tracks and insert them
        loop = asyncio.get_event_loop()
        tracks = await loop.run_in_executor(None, sc.get_album_tracks, req.spotify_id)
        with conn:
            # Insert album-type pin for the album itself
            conn.execute("""
                INSERT OR IGNORE INTO spotify_pins
                  (item_type, spotify_id, name, artist_id, artist_name,
                   album_id, album_name, image_url)
                VALUES ('album', ?, ?, ?, ?, ?, ?, ?)
            """, (req.spotify_id, req.name, req.artist_id, req.artist_name,
                  req.spotify_id, req.name, req.image_url))
            # Insert each track
            for t in tracks:
                conn.execute("""
                    INSERT OR IGNORE INTO spotify_pins
                      (item_type, spotify_id, name, artist_id, artist_name,
                       album_id, album_name, track_number, disc_number, duration_ms, image_url)
                    VALUES ('track', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (t["id"], t["name"], t.get("artist_id"), t.get("artist_name"),
                      t["album_id"], t["album_name"],
                      t.get("track_number"), t.get("disc_number", 1),
                      t.get("duration_ms"), t.get("image_url")))
        conn.close()
        return {"status": "pinned", "type": "album", "tracks_added": len(tracks)}

    else:
        # Artist or track — single row insert
        with conn:
            conn.execute("""
                INSERT OR IGNORE INTO spotify_pins
                  (item_type, spotify_id, name, artist_id, artist_name,
                   album_id, album_name, track_number, disc_number, duration_ms, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (req.item_type, req.spotify_id, req.name,
                  req.artist_id, req.artist_name,
                  req.album_id, req.album_name,
                  req.track_number, req.disc_number or 1,
                  req.duration_ms, req.image_url))
        conn.close()
        return {"status": "pinned", "type": req.item_type}


@router.delete("/pin/{spotify_id}")
def unpin_item(spotify_id: str):
    """
    Unpin an item. If a track/album is unpinned, only that item is removed.
    Unpinning an artist removes the artist-type pin but leaves any track/album pins.
    """
    from database import get_db
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM spotify_pins WHERE spotify_id=?", (spotify_id,))
    conn.close()
    return {"status": "unpinned", "spotify_id": spotify_id}


@router.get("/pin/check/{spotify_id}")
def check_pinned(spotify_id: str):
    from database import get_db
    conn = get_db()
    row = conn.execute(
        "SELECT id, item_type FROM spotify_pins WHERE spotify_id=? LIMIT 1",
        (spotify_id,)
    ).fetchone()
    conn.close()
    return {"pinned": row is not None, "type": dict(row)["item_type"] if row else None}


# ── Pinned library browse endpoints ─────────────────────────

@router.get("/pins/artists")
def pinned_artists():
    """Return all artists that appear in the pinned library (union of artist pins + track/album pin artist_ids)."""
    from database import get_db
    conn = get_db()
    rows = conn.execute("""
        SELECT spotify_id, name, image_url FROM spotify_pins WHERE item_type='artist'
        UNION
        SELECT DISTINCT artist_id AS spotify_id, artist_name AS name, image_url
          FROM spotify_pins WHERE item_type IN ('album','track') AND artist_id IS NOT NULL
        ORDER BY name COLLATE NOCASE
    """).fetchall()
    conn.close()
    # Deduplicate by spotify_id (UNION should handle it, but be safe)
    seen = set()
    artists = []
    for r in rows:
        d = dict(r)
        if d["spotify_id"] not in seen:
            seen.add(d["spotify_id"])
            artists.append(d)
    return {"artists": artists}


@router.get("/pins/albums/{artist_id}")
def pinned_albums(artist_id: str):
    """Return albums for an artist that have pinned tracks, or artist-type pin info."""
    from database import get_db
    conn = get_db()

    # Check if this artist is an artist-type pin (browse live from Spotify)
    artist_pin = conn.execute(
        "SELECT * FROM spotify_pins WHERE item_type='artist' AND spotify_id=?",
        (artist_id,)
    ).fetchone()

    # Get albums derived from track/album pins
    rows = conn.execute("""
        SELECT DISTINCT album_id AS spotify_id, album_name AS name, image_url
          FROM spotify_pins WHERE artist_id=? AND album_id IS NOT NULL
        ORDER BY name COLLATE NOCASE
    """, (artist_id,)).fetchall()
    conn.close()

    return {
        "artist_id":    artist_id,
        "albums":       [dict(r) for r in rows],
        "has_artist_pin": artist_pin is not None,
        # If artist-type pin with no albums pinned, front-end should offer "Browse live from Spotify"
        "live_browse_available": artist_pin is not None and len(rows) == 0,
    }


@router.get("/pins/tracks/{album_id}")
def pinned_tracks(album_id: str):
    """Return pinned tracks for an album, in track/disc order."""
    from database import get_db
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM spotify_pins
          WHERE album_id=? AND item_type='track'
          ORDER BY disc_number, track_number
    """, (album_id,)).fetchall()
    conn.close()
    return {"album_id": album_id, "tracks": [dict(r) for r in rows]}
```

---

### Replace `#spotify-browser` content in `templates/index.html`

Replace the placeholder `<p>` inside `#spotify-browser` with the full Spotify browser structure:

```html
<div id="spotify-browser" class="hidden">

  <!-- Top controls row: view toggle + search mode toggle -->
  <div class="spotify-top-controls">
    <div class="spotify-view-toggle">
      <button class="sp-toggle-btn sp-toggle-active" id="sp-view-artists" data-view="artists">
        Artists
      </button>
      <button class="sp-toggle-btn" id="sp-view-playlists" data-view="playlists">
        Playlists
      </button>
    </div>
    <div class="spotify-search-area">
      <input type="text" id="sp-search-input" class="search-input" 
             placeholder="Search…" autocomplete="off">
      <div class="search-filters">
        <label><input type="radio" name="sp-search-scope" value="library" checked> Library</label>
        <label><input type="radio" name="sp-search-scope" value="spotify"> All Spotify</label>
      </div>
    </div>
  </div>

  <!-- Breadcrumb -->
  <div id="sp-breadcrumb" class="breadcrumb hidden"></div>

  <!-- File list (reuses same CSS as mp3 browser) -->
  <div id="sp-file-list" class="file-list hidden"></div>

  <!-- Empty state -->
  <div id="sp-empty-state" class="empty-state hidden">
    <p>📌 No Spotify items pinned yet.</p>
    <p>Use the search bar to find artists, albums, or tracks and pin them to your library.</p>
  </div>

</div>
```

---

### `static/style.css` additions — append to end of file

```css
/* ============================================================
   SPOTIFY BROWSER — Phase 2
   ============================================================ */

.spotify-top-controls {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

/* View toggle: Artists / Playlists */
.spotify-view-toggle {
  display: flex;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 3px;
  flex-shrink: 0;
}
.sp-toggle-btn {
  padding: 6px 18px;
  font-size: 0.85rem;
  font-weight: 500;
  background: none;
  border: none;
  color: var(--text-secondary);
  border-radius: calc(var(--radius) - 2px);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.sp-toggle-btn:hover { color: var(--text-primary); }
.sp-toggle-btn.sp-toggle-active {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

/* Search area reuses .search-input + .search-filters from main styles */
.spotify-search-area {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 200px;
}

/* Spotify row — thumbnail image */
.sp-thumb {
  width: 36px;
  height: 36px;
  border-radius: 3px;
  object-fit: cover;
  flex-shrink: 0;
  background: var(--bg-tertiary);
}
.sp-thumb-placeholder {
  width: 36px;
  height: 36px;
  border-radius: 3px;
  background: var(--bg-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  flex-shrink: 0;
  color: var(--text-muted);
}

/* Track number column */
.sp-track-num {
  width: 28px;
  text-align: right;
  font-size: 0.8rem;
  color: var(--text-muted);
  flex-shrink: 0;
  font-family: var(--font-mono);
}

/* Duration column */
.sp-duration {
  font-size: 0.8rem;
  color: var(--text-muted);
  font-family: var(--font-mono);
  white-space: nowrap;
  flex-shrink: 0;
}

/* Year column on album rows */
.sp-year {
  font-size: 0.78rem;
  color: var(--text-muted);
  flex-shrink: 0;
}

/* Pin button */
.sp-pin-btn {
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 10px;
  font-size: 0.75rem;
  cursor: pointer;
  color: var(--text-muted);
  white-space: nowrap;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.sp-pin-btn:hover    { background: var(--bg-tertiary); color: var(--text-secondary); }
.sp-pin-btn.pinned   { color: #1db954; border-color: rgba(29,185,84,0.4); }
.sp-pin-btn.pinned:hover { background: rgba(29,185,84,0.1); }

/* Live-from-Spotify info banner inside file list */
.sp-live-banner {
  padding: 10px 14px;
  background: rgba(29,185,84,0.08);
  border-bottom: 1px solid var(--border);
  font-size: 0.8rem;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 8px;
}
.sp-live-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #1db954;
  flex-shrink: 0;
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}

/* Search result type separator */
.sp-result-section-header {
  padding: 8px 14px 4px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}
```

---

### `static/app.js` — append Spotify browser JS

```javascript
/* ============================================================
   SPOTIFY — Phase 2: Library browser, pin system, search
   ============================================================ */

// ── Spotify browser state ─────────────────────────────────────
const sp = {
    view:        'artists',      // 'artists' | 'playlists'
    searchScope: 'library',      // 'library' | 'spotify'
    breadcrumb:  [],             // [{label, action}]
    searchTimer: null,
};

// ── Init Spotify browser (called after auth confirmed) ────────
document.addEventListener('DOMContentLoaded', () => {
    // Wait for auth check then init browser
    // Use MutationObserver to detect when #spotify-browser becomes visible
    const browserEl = document.getElementById('spotify-browser');
    if (!browserEl) return;

    const observer = new MutationObserver(() => {
        if (!browserEl.classList.contains('hidden')) {
            initSpotifyBrowser();
            observer.disconnect();
        }
    });
    observer.observe(browserEl, { attributes: true, attributeFilter: ['class'] });

    // If already visible on load (auth already stored)
    if (!browserEl.classList.contains('hidden')) {
        initSpotifyBrowser();
    }
});

function initSpotifyBrowser() {
    // View toggle
    document.querySelectorAll('.sp-toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            sp.view = btn.dataset.view;
            document.querySelectorAll('.sp-toggle-btn').forEach(b => b.classList.remove('sp-toggle-active'));
            btn.classList.add('sp-toggle-active');
            sp.breadcrumb = [];
            if (sp.view === 'artists')   loadSpotifyArtists();
            else                          loadSpotifyPlaylists();
        });
    });

    // Search
    const searchInput = document.getElementById('sp-search-input');
    searchInput?.addEventListener('input', () => {
        clearTimeout(sp.searchTimer);
        const q = searchInput.value.trim();
        if (!q) { exitSpotifySearch(); return; }
        sp.searchTimer = setTimeout(() => runSpotifySearch(q), 300);
    });
    searchInput?.addEventListener('keydown', e => {
        if (e.key === 'Escape') { searchInput.value = ''; exitSpotifySearch(); }
    });
    document.querySelectorAll('[name="sp-search-scope"]').forEach(r => {
        r.addEventListener('change', () => {
            sp.searchScope = r.value;
            const q = document.getElementById('sp-search-input')?.value.trim();
            if (q) runSpotifySearch(q);
        });
    });

    // Initial load
    loadSpotifyArtists();
}

// ── Breadcrumb ────────────────────────────────────────────────

function renderSpBreadcrumb() {
    const el = document.getElementById('sp-breadcrumb');
    if (!el) return;
    if (!sp.breadcrumb.length) {
        el.classList.add('hidden');
        return;
    }
    const crumbs = [{ label: 'Spotify', action: () => {
        sp.breadcrumb = [];
        if (sp.view === 'artists') loadSpotifyArtists();
        else loadSpotifyPlaylists();
    }}];

    let html = `<a href="#" class="crumb-link sp-crumb-0">Spotify</a>`;
    sp.breadcrumb.forEach((c, i) => {
        html += `<span class="crumb-sep"> / </span>`;
        if (i < sp.breadcrumb.length - 1) {
            html += `<a href="#" class="crumb-link sp-crumb-${i+1}">${escHtml(c.label)}</a>`;
        } else {
            html += `<span class="crumb-current">${escHtml(c.label)}</span>`;
        }
    });
    el.innerHTML = html;
    el.classList.remove('hidden');

    // Attach click handlers
    el.querySelector('.sp-crumb-0')?.addEventListener('click', e => {
        e.preventDefault();
        sp.breadcrumb = [];
        if (sp.view === 'artists') loadSpotifyArtists();
        else loadSpotifyPlaylists();
    });
    sp.breadcrumb.forEach((c, i) => {
        if (i < sp.breadcrumb.length - 1) {
            el.querySelector(`.sp-crumb-${i+1}`)?.addEventListener('click', e => {
                e.preventDefault();
                sp.breadcrumb = sp.breadcrumb.slice(0, i + 1);
                c.action();
            });
        }
    });
}

// ── List helpers ──────────────────────────────────────────────

function spShowList(rows) {
    const list = document.getElementById('sp-file-list');
    const empty = document.getElementById('sp-empty-state');
    if (!list) return;
    if (!rows.length) {
        list.classList.add('hidden');
        empty?.classList.remove('hidden');
        return;
    }
    empty?.classList.add('hidden');
    list.innerHTML = rows.join('');
    list.classList.remove('hidden');
    attachSpListeners();
}

function spSetLoading() {
    const list = document.getElementById('sp-file-list');
    if (list) {
        list.innerHTML = '<div class="loading-row">Loading…</div>';
        list.classList.remove('hidden');
    }
    document.getElementById('sp-empty-state')?.classList.add('hidden');
}

function spFormatDuration(ms) {
    if (!ms) return '';
    const s = Math.floor(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// ── Row renderers ─────────────────────────────────────────────

function renderSpArtistRow(a, isPinned) {
    const img = a.image_url
        ? `<img class="sp-thumb" src="${escHtml(a.image_url)}" alt="" loading="lazy">`
        : `<span class="sp-thumb-placeholder">🎤</span>`;
    const pinLabel = isPinned ? '📌 Pinned' : '+ Pin';
    return `
    <div class="file-row folder-row">
      ${img}
      <span class="file-name folder-name-link sp-artist-link"
            data-id="${escHtml(a.spotify_id || a.id)}"
            data-name="${escHtml(a.name)}">${escHtml(a.name)}</span>
      <span class="file-meta"></span>
      <div class="file-actions">
        <button class="sp-pin-btn ${isPinned ? 'pinned' : ''}"
                data-action="pin" data-type="artist"
                data-id="${escHtml(a.spotify_id || a.id)}"
                data-name="${escHtml(a.name)}"
                data-image="${escHtml(a.image_url || '')}">${pinLabel}</button>
        <button class="btn-secondary sp-play-btn"
                data-mode="browser" data-context="artist"
                data-id="${escHtml(a.spotify_id || a.id)}">▶ Browser</button>
        <button class="btn-primary sp-play-btn"
                data-mode="sonos" data-context="artist"
                data-id="${escHtml(a.spotify_id || a.id)}">▶ Sonos</button>
      </div>
    </div>`;
}

function renderSpAlbumRow(al, isPinned) {
    const img = al.image_url
        ? `<img class="sp-thumb" src="${escHtml(al.image_url)}" alt="" loading="lazy">`
        : `<span class="sp-thumb-placeholder">💿</span>`;
    const pinLabel = isPinned ? '📌 Pinned' : '+ Pin';
    return `
    <div class="file-row folder-row">
      ${img}
      <span class="file-name folder-name-link sp-album-link"
            data-id="${escHtml(al.spotify_id || al.id)}"
            data-name="${escHtml(al.name)}"
            data-artist-id="${escHtml(al.artist_id || '')}"
            data-artist-name="${escHtml(al.artist_name || '')}">${escHtml(al.name)}</span>
      <span class="file-meta sp-year">${escHtml(al.release_year || '')}</span>
      <div class="file-actions">
        <button class="sp-pin-btn ${isPinned ? 'pinned' : ''}"
                data-action="pin" data-type="album"
                data-id="${escHtml(al.spotify_id || al.id)}"
                data-name="${escHtml(al.name)}"
                data-artist-id="${escHtml(al.artist_id || '')}"
                data-artist-name="${escHtml(al.artist_name || '')}"
                data-image="${escHtml(al.image_url || '')}">${pinLabel}</button>
        <button class="btn-secondary sp-play-btn"
                data-mode="browser" data-context="album"
                data-id="${escHtml(al.spotify_id || al.id)}">▶ Browser</button>
        <button class="btn-primary sp-play-btn"
                data-mode="sonos" data-context="album"
                data-id="${escHtml(al.spotify_id || al.id)}">▶ Sonos</button>
      </div>
    </div>`;
}

function renderSpTrackRow(t, isPinned) {
    const num  = t.track_number ? `<span class="sp-track-num">${t.track_number}</span>` : '';
    const dur  = `<span class="sp-duration">${spFormatDuration(t.duration_ms)}</span>`;
    const pinLabel = isPinned ? '📌' : '+';
    return `
    <div class="file-row file-row-music">
      ${num}
      <span class="file-name">${escHtml(t.name)}</span>
      ${dur}
      <div class="file-actions">
        <button class="sp-pin-btn ${isPinned ? 'pinned' : ''}"
                data-action="pin" data-type="track"
                data-id="${escHtml(t.spotify_id || t.id)}"
                data-name="${escHtml(t.name)}"
                data-artist-id="${escHtml(t.artist_id || '')}"
                data-artist-name="${escHtml(t.artist_name || '')}"
                data-album-id="${escHtml(t.album_id || '')}"
                data-album-name="${escHtml(t.album_name || '')}"
                data-track-num="${t.track_number || ''}"
                data-disc-num="${t.disc_number || 1}"
                data-duration="${t.duration_ms || ''}"
                data-image="${escHtml(t.image_url || '')}">${pinLabel}</button>
        <button class="btn-secondary sp-play-btn"
                data-mode="browser" data-context="track"
                data-id="${escHtml(t.spotify_id || t.id)}"
                data-name="${escHtml(t.name)}"
                data-uri="spotify:track:${escHtml(t.spotify_id || t.id)}">▶ Browser</button>
        <button class="btn-primary sp-play-btn"
                data-mode="sonos" data-context="track"
                data-id="${escHtml(t.spotify_id || t.id)}"
                data-name="${escHtml(t.name)}"
                data-uri="spotify:track:${escHtml(t.spotify_id || t.id)}">▶ Sonos</button>
      </div>
    </div>`;
}

// ── Pin IDs cache (avoid DB round-trips on every render) ──────
const pinnedIds = new Set();

async function refreshPinnedIds() {
    // Lightweight: just list all spotify_ids from pins
    // No dedicated endpoint needed — derive from existing artist/album/track queries
    // Or add a simple GET /api/spotify/pins/ids endpoint for efficiency
    // For now: populate lazily per-item via check-pinned calls
}

// ── Load views ────────────────────────────────────────────────

async function loadSpotifyArtists() {
    renderSpBreadcrumb();
    spSetLoading();
    try {
        const res  = await fetch('/api/spotify/pins/artists');
        const data = await res.json();
        const artists = data.artists || [];

        if (!artists.length) {
            spShowList([]);
            return;
        }

        // Check which are pinned (all in this view are pinned by definition)
        const rows = artists.map(a => renderSpArtistRow(a, true));
        spShowList(rows);
    } catch (err) {
        document.getElementById('sp-file-list').innerHTML =
            '<div class="loading-row error-row">Failed to load library</div>';
    }
}

async function loadSpotifyAlbumsForArtist(artistId, artistName) {
    sp.breadcrumb = [{ label: artistName, action: () => loadSpotifyAlbumsForArtist(artistId, artistName) }];
    renderSpBreadcrumb();
    spSetLoading();
    try {
        const res  = await fetch(`/api/spotify/pins/albums/${encodeURIComponent(artistId)}`);
        const data = await res.json();
        const albums = data.albums || [];
        const rows = [];

        if (data.live_browse_available) {
            // Artist-type pin with no album pins yet — load live from Spotify
            rows.push(`<div class="sp-live-banner"><span class="sp-live-dot"></span>Browsing live from Spotify — pin albums to save to your library</div>`);
            const liveRes  = await fetch(`/api/spotify/artist/${encodeURIComponent(artistId)}/albums`);
            const liveData = await liveRes.json();
            const liveAlbums = liveData.albums || [];
            // Check which are pinned
            for (const al of liveAlbums) {
                const pinRes = await fetch(`/api/spotify/pin/check/${encodeURIComponent(al.id)}`);
                const pinData = await pinRes.json();
                rows.push(renderSpAlbumRow({...al, spotify_id: al.id, artist_id: artistId, artist_name: artistName}, pinData.pinned));
            }
        } else if (albums.length === 0) {
            // Has track pins but no album-level grouping (shouldn't happen, but handle)
            rows.push('<div class="loading-row muted-row">No albums pinned for this artist</div>');
        } else {
            for (const al of albums) {
                const pinRes = await fetch(`/api/spotify/pin/check/${encodeURIComponent(al.spotify_id)}`);
                const pinData = await pinRes.json();
                rows.push(renderSpAlbumRow(al, pinData.pinned));
            }
        }

        if (rows.length > 0) {
            const list = document.getElementById('sp-file-list');
            if (list) {
                list.innerHTML = rows.join('');
                list.classList.remove('hidden');
                document.getElementById('sp-empty-state')?.classList.add('hidden');
                attachSpListeners();
            }
        } else {
            spShowList([]);
        }
    } catch (err) {
        document.getElementById('sp-file-list').innerHTML =
            '<div class="loading-row error-row">Failed to load albums</div>';
    }
}

async function loadSpotifyTracksForAlbum(albumId, albumName, artistId, artistName) {
    // Try pinned tracks first
    spSetLoading();
    try {
        const res  = await fetch(`/api/spotify/pins/tracks/${encodeURIComponent(albumId)}`);
        const data = await res.json();
        let tracks = data.tracks || [];

        if (!tracks.length) {
            // No tracks pinned — load live
            const liveRes  = await fetch(`/api/spotify/album/${encodeURIComponent(albumId)}/tracks`);
            const liveData = await liveRes.json();
            tracks = (liveData.tracks || []).map(t => ({ ...t, spotify_id: t.id }));
        }

        const rows = [];
        if (!tracks.length) {
            rows.push('<div class="loading-row muted-row">No tracks found</div>');
        } else {
            for (const t of tracks) {
                const pinRes = await fetch(`/api/spotify/pin/check/${encodeURIComponent(t.spotify_id || t.id)}`);
                const pinData = await pinRes.json();
                rows.push(renderSpTrackRow(t, pinData.pinned));
            }
        }

        const list = document.getElementById('sp-file-list');
        if (list) {
            list.innerHTML = rows.join('');
            list.classList.remove('hidden');
            document.getElementById('sp-empty-state')?.classList.add('hidden');
            attachSpListeners();
        }
    } catch (err) {
        document.getElementById('sp-file-list').innerHTML =
            '<div class="loading-row error-row">Failed to load tracks</div>';
    }
}

async function loadSpotifyPlaylists() {
    sp.breadcrumb = [];
    renderSpBreadcrumb();
    spSetLoading();
    try {
        const res  = await fetch('/api/spotify/playlists');
        const data = await res.json();
        const playlists = data.playlists || [];
        if (!playlists.length) { spShowList([]); return; }
        const rows = playlists.map(pl => `
        <div class="file-row folder-row">
          ${pl.image_url ? `<img class="sp-thumb" src="${escHtml(pl.image_url)}" alt="" loading="lazy">` : '<span class="sp-thumb-placeholder">🎵</span>'}
          <span class="file-name folder-name-link sp-playlist-link"
                data-id="${escHtml(pl.id)}" data-name="${escHtml(pl.name)}">${escHtml(pl.name)}</span>
          <span class="file-meta">${pl.track_count} tracks</span>
          <div class="file-actions">
            <button class="btn-secondary sp-play-btn" data-mode="browser" data-context="playlist" data-id="${escHtml(pl.id)}">▶ Browser</button>
            <button class="btn-primary sp-play-btn" data-mode="sonos" data-context="playlist" data-id="${escHtml(pl.id)}">▶ Sonos</button>
          </div>
        </div>`);
        spShowList(rows);
    } catch (err) {
        document.getElementById('sp-file-list').innerHTML =
            '<div class="loading-row error-row">Failed to load playlists</div>';
    }
}

async function loadSpotifyPlaylistTracks(playlistId, playlistName) {
    sp.breadcrumb = [{ label: playlistName, action: () => loadSpotifyPlaylistTracks(playlistId, playlistName) }];
    renderSpBreadcrumb();
    spSetLoading();
    try {
        const res  = await fetch(`/api/spotify/playlist/${encodeURIComponent(playlistId)}/tracks`);
        const data = await res.json();
        const tracks = data.tracks || [];
        const rows = await Promise.all(tracks.map(async t => {
            const pinRes  = await fetch(`/api/spotify/pin/check/${encodeURIComponent(t.id)}`);
            const pinData = await pinRes.json();
            return renderSpTrackRow({...t, spotify_id: t.id}, pinData.pinned);
        }));
        spShowList(rows.length ? rows : ['<div class="loading-row muted-row">No tracks</div>']);
    } catch (err) {
        document.getElementById('sp-file-list').innerHTML =
            '<div class="loading-row error-row">Failed to load playlist</div>';
    }
}

// ── Search ────────────────────────────────────────────────────

async function runSpotifySearch(q) {
    sp.breadcrumb = [{ label: `"${q}"`, action: () => runSpotifySearch(q) }];
    renderSpBreadcrumb();
    spSetLoading();

    const scope = document.querySelector('[name="sp-search-scope"]:checked')?.value || 'library';
    const rows  = [];

    if (scope === 'library') {
        // Search pinned items only (artist_name and name LIKE %q%)
        try {
            const [arRes, alRes, trRes] = await Promise.all([
                fetch(`/api/spotify/pins/artists`),
                fetch(`/api/spotify/search?q=${encodeURIComponent(q)}&types=artist`), // fallback: search DB
                fetch(`/api/spotify/search?q=${encodeURIComponent(q)}&types=track`),
            ]);
            // For library search, query DB directly via a new endpoint (see note below)
            // Simple approach: load all pinned artists and filter client-side for MVP
            const artistData = await arRes.json();
            const filtered = (artistData.artists || []).filter(a =>
                a.name.toLowerCase().includes(q.toLowerCase())
            );
            if (filtered.length) {
                rows.push('<div class="sp-result-section-header">Artists</div>');
                filtered.forEach(a => rows.push(renderSpArtistRow(a, true)));
            }
            if (!rows.length) {
                rows.push('<div class="loading-row muted-row">No pinned results for "' + escHtml(q) + '"</div>');
            }
        } catch (err) {
            rows.push('<div class="loading-row error-row">Search error</div>');
        }
    } else {
        // Search all of Spotify
        try {
            const res  = await fetch(`/api/spotify/search?q=${encodeURIComponent(q)}&types=artist,album,track`);
            const data = await res.json();

            if (data.artists?.length) {
                rows.push('<div class="sp-result-section-header">Artists</div>');
                for (const a of data.artists) {
                    const pinRes  = await fetch(`/api/spotify/pin/check/${encodeURIComponent(a.id)}`);
                    const pinData = await pinRes.json();
                    rows.push(renderSpArtistRow({...a, spotify_id: a.id}, pinData.pinned));
                }
            }
            if (data.albums?.length) {
                rows.push('<div class="sp-result-section-header">Albums</div>');
                for (const al of data.albums) {
                    const pinRes  = await fetch(`/api/spotify/pin/check/${encodeURIComponent(al.id)}`);
                    const pinData = await pinRes.json();
                    rows.push(renderSpAlbumRow({...al, spotify_id: al.id}, pinData.pinned));
                }
            }
            if (data.tracks?.length) {
                rows.push('<div class="sp-result-section-header">Tracks</div>');
                for (const t of data.tracks) {
                    const pinRes  = await fetch(`/api/spotify/pin/check/${encodeURIComponent(t.id)}`);
                    const pinData = await pinRes.json();
                    rows.push(renderSpTrackRow({...t, spotify_id: t.id}, pinData.pinned));
                }
            }
            if (!rows.length) {
                rows.push('<div class="loading-row muted-row">No results for "' + escHtml(q) + '"</div>');
            }
        } catch (err) {
            rows.push('<div class="loading-row error-row">Search error</div>');
        }
    }

    spShowList(rows);
}

function exitSpotifySearch() {
    sp.breadcrumb = [];
    if (sp.view === 'artists')   loadSpotifyArtists();
    else                          loadSpotifyPlaylists();
}

// ── Event delegation for dynamic list rows ────────────────────

function attachSpListeners() {
    const list = document.getElementById('sp-file-list');
    if (!list) return;

    // Artist drill-in
    list.querySelectorAll('.sp-artist-link').forEach(el => {
        el.addEventListener('click', e => {
            e.preventDefault();
            const id   = el.dataset.id;
            const name = el.dataset.name;
            sp.breadcrumb = [{ label: name, action: () => loadSpotifyAlbumsForArtist(id, name) }];
            loadSpotifyAlbumsForArtist(id, name);
        });
    });

    // Album drill-in
    list.querySelectorAll('.sp-album-link').forEach(el => {
        el.addEventListener('click', e => {
            e.preventDefault();
            const albumId    = el.dataset.id;
            const albumName  = el.dataset.name;
            const artistId   = el.dataset.artistId;
            const artistName = el.dataset.artistName;
            const existing = sp.breadcrumb.filter(c => c.label === artistName);
            if (!existing.length) {
                sp.breadcrumb = [
                    { label: artistName, action: () => loadSpotifyAlbumsForArtist(artistId, artistName) },
                    { label: albumName,  action: () => loadSpotifyTracksForAlbum(albumId, albumName, artistId, artistName) },
                ];
            } else {
                sp.breadcrumb = [
                    ...sp.breadcrumb.slice(0, sp.breadcrumb.findIndex(c => c.label === artistName) + 1),
                    { label: albumName, action: () => loadSpotifyTracksForAlbum(albumId, albumName, artistId, artistName) },
                ];
            }
            renderSpBreadcrumb();
            loadSpotifyTracksForAlbum(albumId, albumName, artistId, artistName);
        });
    });

    // Playlist drill-in
    list.querySelectorAll('.sp-playlist-link').forEach(el => {
        el.addEventListener('click', e => {
            e.preventDefault();
            loadSpotifyPlaylistTracks(el.dataset.id, el.dataset.name);
        });
    });

    // Pin/Unpin
    list.querySelectorAll('[data-action="pin"]').forEach(btn => {
        btn.addEventListener('click', () => toggleSpotifyPin(btn));
    });

    // Play buttons (stubs — Phase 3 wires these up)
    list.querySelectorAll('.sp-play-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.spotifyPlay) {
                spotifyPlay(btn.dataset.mode, btn.dataset.context, btn.dataset.id, btn.dataset.uri, btn.dataset.name);
            } else {
                console.log('[Phase 3] Spotify play:', btn.dataset);
            }
        });
    });
}

// ── Pin / Unpin ───────────────────────────────────────────────

async function toggleSpotifyPin(btn) {
    const id      = btn.dataset.id;
    const isPinned = btn.classList.contains('pinned');

    if (isPinned) {
        await fetch(`/api/spotify/pin/${encodeURIComponent(id)}`, { method: 'DELETE' });
        btn.textContent = btn.dataset.type === 'track' ? '+' : '+ Pin';
        btn.classList.remove('pinned');
        showToast('Unpinned', 'success');
    } else {
        const body = {
            item_type:    btn.dataset.type,
            spotify_id:   id,
            name:         btn.dataset.name,
            artist_id:    btn.dataset.artistId   || null,
            artist_name:  btn.dataset.artistName  || null,
            album_id:     btn.dataset.albumId     || null,
            album_name:   btn.dataset.albumName   || null,
            track_number: btn.dataset.trackNum ? Number(btn.dataset.trackNum) : null,
            disc_number:  btn.dataset.discNum  ? Number(btn.dataset.discNum)  : 1,
            duration_ms:  btn.dataset.duration ? Number(btn.dataset.duration) : null,
            image_url:    btn.dataset.image    || null,
        };
        const res  = await fetch('/api/spotify/pin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        if (data.status === 'pinned') {
            btn.textContent = btn.dataset.type === 'track' ? '📌' : '📌 Pinned';
            btn.classList.add('pinned');
            const msg = btn.dataset.type === 'album'
                ? `Album pinned (${data.tracks_added} tracks added)`
                : `${btn.dataset.type.charAt(0).toUpperCase() + btn.dataset.type.slice(1)} pinned`;
            showToast(msg, 'success');
        }
    }
}
```

---

## New API Endpoints (Phase 2)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/spotify/pin` | Pin an artist, album (+ all tracks), or track |
| `DELETE` | `/api/spotify/pin/{spotify_id}` | Unpin item by Spotify ID |
| `GET` | `/api/spotify/pin/check/{spotify_id}` | Check if item is pinned |
| `GET` | `/api/spotify/pins/artists` | All pinned artists |
| `GET` | `/api/spotify/pins/albums/{artist_id}` | Albums for an artist in pinned library |
| `GET` | `/api/spotify/pins/tracks/{album_id}` | Tracks for an album in pinned library |

---

## Validation Steps

1. Click **Spotify** tab → Artists view loads (empty state if nothing pinned).
2. Switch to search bar, select "All Spotify", search "Massive Attack" → Artists, Albums, Tracks sections appear.
3. Click "**+ Pin**" on Massive Attack → "Artist pinned" toast. Switch to Library search, search "massive" → Massive Attack appears.
4. Click Massive Attack name → albums load (live from Spotify, with "Browsing live from Spotify" banner).
5. Click an album "Mezzanine" → tracks load. Click "**+ Pin**" on album → "Album pinned (11 tracks added)" toast. Breadcrumb: `Spotify / Massive Attack / Mezzanine`.
6. Return to artist list (click "Spotify" breadcrumb) → Massive Attack still shows, now with 📌 Pinned badge.
7. Click Massive Attack → Mezzanine appears in the albums view (no longer "live browse" banner).
8. Click Mezzanine → 11 tracks shown from DB (no API call).
9. Pin a single track. `sqlite3 sonosweb.db "SELECT COUNT(*) FROM spotify_pins WHERE item_type='track';"` → count matches.
10. Unpin the track → pin button resets to "+".
11. Switch to **Playlists** toggle → your Spotify playlists appear.
12. Click a playlist → tracks appear with Pin buttons.
13. Press Escape in search → returns to pinned artists view.

---

## Notes & Gotchas

**Per-item pin check API calls in search results:** The current implementation calls `/api/spotify/pin/check/{id}` for each result row in search. For 10-20 results this is acceptable (10-20 fast DB reads). If you see slowness, add a batch endpoint `POST /api/spotify/pin/check-batch` that accepts a list of IDs and returns a set of which are pinned.

**`await` inside `forEach`** won't work as expected for serial async operations. The `loadSpotifyAlbumsForArtist` and similar functions use `for...of` loops for pin-check calls. Do not convert these to `.forEach()` with async callbacks.

**Library search (pinned only) is basic in this phase:** It fetches all pinned artists and filters client-side. This is fine for personal libraries (typically < 100 artists). For Phase 3 or beyond, add a proper `GET /api/spotify/pins/search?q=` DB endpoint using SQL `LIKE` across the pins table.

**Album cover images:** Stored in `image_url` during pin. On track rows we don't show album art (keeps track rows slim like the mp3 browser). Images are shown on artist and album rows only.

**`data-artist-id` → camelCase in JS:** HTML `data-artist-id` becomes `btn.dataset.artistId` in JS (auto-camelCased by the DOM). This is expected browser behavior; do not rename the attributes.
