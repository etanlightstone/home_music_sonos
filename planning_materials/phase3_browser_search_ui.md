# Phase 3: Music Browser UI — File Listing API, Search, and Full Frontend

## What This Phase Builds
- `routers/files.py` — API endpoints for browsing directory contents and multi-facet search
- Full replacement of the placeholder browser area in `static/app.js` with working file/folder navigation, breadcrumbs, and search
- Empty state and loading states
- Sonos and Browser play buttons wired to **stub calls** (the buttons appear and are clickable; actual Sonos and browser playback is implemented in Phase 4)

---

## Full App Context (Read Before Starting)
You are building **SonosWeb** — a dark-themed web app for browsing and playing music from a remote SFTP/FTP server on Sonos speakers. Backend is Python FastAPI. Frontend is vanilla HTML/CSS/JS (no React/Vue).

**Already built (do not re-implement):**
- `database.py` — `get_db()`, `init_db()`
- `routers/settings.py` — `get_settings()` returns dict with keys: `sonos_ip`, `server_type`, `server_host`, `server_port`, `server_user`, `server_password`, `server_path`, `webserver_host`
- `routers/proxy.py` — `build_proxy_url(rel_path, settings)` returns the full HTTP URL for a file; `GET /api/proxy/{path}` streams the file
- `routers/index_router.py` — index start/status/interrupt endpoints
- `services/indexer.py` — background indexing
- `templates/index.html` — complete HTML shell (two tabs, playbar placeholder, search bar area, `#browser-area`, `#file-list`, `#breadcrumb`, `#empty-state`)
- `static/style.css` — complete dark theme with all CSS classes needed (`.file-row`, `.folder-row`, `.file-icon`, `.ext-badge`, `.btn-primary`, `.btn-secondary`, `.breadcrumb`, etc.)
- `static/app.js` — tab switching, settings form, index polling (`updateIndexUI`, `startIndexPoll`)

**The `entries` DB table** (already created) has columns:
- `path` — relative path from server root, e.g. `/Rock/song.mp3`
- `name` — basename, e.g. `song.mp3`
- `parent_path` — parent dir, e.g. `/Rock`; root items have `parent_path = /`
- `is_directory` — 1 or 0
- `size` — bytes (NULL for dirs)
- `modified` — ISO datetime string (NULL if unknown)
- `extension` — lowercase e.g. `mp3` (NULL for dirs)

---

## Files to Create / Modify

```
sonosweb/
├── routers/
│   └── files.py          ← CREATE
├── static/
│   └── app.js            ← MODIFY (add browser + search logic)
└── main.py               ← MODIFY (include files router)
```

---

## Implementation

### `routers/files.py`

```python
from fastapi import APIRouter, Query
from database import get_db

router = APIRouter()


def _row_to_dict(row) -> dict:
    d = dict(row)
    d['is_directory'] = bool(d['is_directory'])
    return d


def _sort_entries(entries: list[dict]) -> list[dict]:
    """Folders first, then files — both alphabetically (case-insensitive)."""
    return sorted(
        entries,
        key=lambda e: (0 if e['is_directory'] else 1, e['name'].lower())
    )


@router.get("/browse")
def browse(path: str = Query(default="/")):
    """
    List entries whose parent_path matches `path`.
    Returns folders first, then music files, both alphabetically.
    """
    conn = get_db()

    # Normalize path
    if not path:
        path = "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    rows = conn.execute(
        "SELECT * FROM entries WHERE parent_path = ? ORDER BY is_directory DESC, name COLLATE NOCASE ASC",
        (path,)
    ).fetchall()
    conn.close()

    entries = _sort_entries([_row_to_dict(r) for r in rows])
    return {"path": path, "entries": entries}


@router.get("/search")
def search(
    q: str = Query(default=""),
    type: str = Query(default="all"),  # all | files | folders
):
    """
    Case-insensitive search across name column.
    type: 'all' searches both files and dirs; 'files' only files; 'folders' only dirs.
    Returns up to 500 results, sorted folders-first then alphabetically.
    """
    if not q.strip():
        return {"query": q, "type": type, "entries": []}

    conn = get_db()
    sql = "SELECT * FROM entries WHERE name LIKE ? COLLATE NOCASE"
    params: list = [f"%{q.strip()}%"]

    if type == "files":
        sql += " AND is_directory = 0"
    elif type == "folders":
        sql += " AND is_directory = 1"

    sql += " ORDER BY is_directory DESC, name COLLATE NOCASE ASC LIMIT 500"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return {"query": q, "type": type, "entries": [_row_to_dict(r) for r in rows]}


@router.get("/folder-files")
def folder_files(path: str = Query(...)):
    """
    Return ALL music files (not directories) under a path, recursively.
    Used to build a play queue for a folder on Sonos or in-browser.
    Results are sorted by path (album/track order).
    """
    conn = get_db()

    # Normalize
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Match entries whose path starts with the given path prefix
    like_pattern = path.rstrip('/') + '/%'
    rows = conn.execute(
        """SELECT * FROM entries
           WHERE is_directory = 0
             AND (parent_path = ? OR path LIKE ?)
           ORDER BY path COLLATE NOCASE ASC""",
        (path, like_pattern)
    ).fetchall()
    conn.close()

    return {"path": path, "files": [_row_to_dict(r) for r in rows]}


@router.get("/index-check")
def index_check():
    """Quick check: are there any entries indexed?"""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    conn.close()
    return {"has_entries": count > 0, "count": count}
```

---

### Modify `main.py`

Add the files router. The complete updated `main.py`:

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from contextlib import asynccontextmanager

from database import init_db
from routers import settings as settings_router
from routers import index_router
from routers import proxy
from routers import files as files_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SonosWeb", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(index_router.router,    prefix="/api/index",    tags=["index"])
app.include_router(proxy.router,           prefix="/api/proxy",    tags=["proxy"])
app.include_router(files_router.router,    prefix="/api/files",    tags=["files"])

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

---

### `static/app.js` — Browser & Search additions

Append all of the following to `app.js` (keep everything from Phases 1 and 2). These additions handle: initial load check, directory navigation, breadcrumbs, file list rendering, and search.

```javascript
/* ============================================================
   PHASE 3 — Browser navigation & search
   ============================================================ */

// ── State ───────────────────────────────────────────────────
let currentBrowserPath = '/';
let isSearchMode = false;

// ── Boot: check index on page load ──────────────────────────
// Add this call inside the existing DOMContentLoaded handler:
//   checkIndexAndLoad();
// OR add a second DOMContentLoaded listener (both work):
document.addEventListener('DOMContentLoaded', () => {
    checkIndexAndLoad();
    initSearch();
});

async function checkIndexAndLoad() {
    try {
        const res = await fetch('/api/files/index-check');
        const data = await res.json();
        if (data.has_entries) {
            loadBrowser('/');
        } else {
            showEmptyState();
        }
    } catch (err) {
        showEmptyState();
    }
}

// ── Empty / loading states ───────────────────────────────────
function showEmptyState() {
    document.getElementById('empty-state')?.classList.remove('hidden');
    document.getElementById('file-list')?.classList.add('hidden');
    document.getElementById('breadcrumb')?.classList.add('hidden');
}

function showFileList() {
    document.getElementById('empty-state')?.classList.add('hidden');
    document.getElementById('file-list')?.classList.remove('hidden');
    document.getElementById('breadcrumb')?.classList.remove('hidden');
}

function setFileListLoading() {
    const list = document.getElementById('file-list');
    if (list) {
        list.innerHTML = '<div class="loading-row">Loading…</div>';
        list.classList.remove('hidden');
    }
}

// ── Breadcrumb ───────────────────────────────────────────────
function renderBreadcrumb(path) {
    const el = document.getElementById('breadcrumb');
    if (!el) return;

    if (isSearchMode) {
        el.innerHTML = '<span class="crumb-current">Search Results</span>';
        el.classList.remove('hidden');
        return;
    }

    const parts = path === '/' ? [] : path.replace(/^\//, '').split('/');
    let html = '<a href="#" class="crumb-link" data-path="/">Home</a>';

    let builtPath = '';
    parts.forEach((part, i) => {
        builtPath += '/' + part;
        html += '<span class="crumb-sep"> / </span>';
        if (i === parts.length - 1) {
            html += `<span class="crumb-current">${escHtml(part)}</span>`;
        } else {
            html += `<a href="#" class="crumb-link" data-path="${escHtml(builtPath)}">${escHtml(part)}</a>`;
        }
    });

    el.innerHTML = html;
    el.classList.remove('hidden');

    // Attach click handlers to crumb links
    el.querySelectorAll('.crumb-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            loadBrowser(link.dataset.path);
        });
    });
}

// ── Load a browser directory ─────────────────────────────────
async function loadBrowser(path) {
    isSearchMode = false;
    currentBrowserPath = path;
    showFileList();
    setFileListLoading();
    renderBreadcrumb(path);

    try {
        const res = await fetch(`/api/files/browse?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        renderFileList(data.entries, false);
    } catch (err) {
        document.getElementById('file-list').innerHTML =
            '<div class="loading-row error-row">Error loading directory</div>';
    }
}

// ── Render file/folder list ──────────────────────────────────
function renderFileList(entries, isSearch) {
    const list = document.getElementById('file-list');
    if (!list) return;

    if (entries.length === 0) {
        list.innerHTML = '<div class="loading-row muted-row">No items found</div>';
        return;
    }

    const rows = entries.map(entry =>
        entry.is_directory
            ? renderFolderRow(entry, isSearch)
            : renderFileRow(entry)
    );
    list.innerHTML = rows.join('');

    // Attach click handlers for folder navigation
    list.querySelectorAll('.folder-name-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            loadBrowser(link.dataset.path);
        });
    });

    // Attach placeholder handlers for Sonos + Browser play
    // These are finalized in Phase 4; for now they log intent
    list.querySelectorAll('.browser-play-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.playInBrowser) {
                playInBrowser(btn.dataset.path, btn.dataset.name);
            } else {
                console.log('[Phase 4] Browser play:', btn.dataset.path);
            }
        });
    });

    list.querySelectorAll('.sonos-play-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.playOnSonos) {
                playOnSonos(btn.dataset.path, btn.dataset.name);
            } else {
                console.log('[Phase 4] Sonos play:', btn.dataset.path);
            }
        });
    });

    list.querySelectorAll('.sonos-folder-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.playFolderOnSonos) {
                playFolderOnSonos(btn.dataset.path, btn.dataset.name);
            } else {
                console.log('[Phase 4] Sonos folder play:', btn.dataset.path);
            }
        });
    });

    list.querySelectorAll('.browser-folder-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.playFolderInBrowser) {
                playFolderInBrowser(btn.dataset.path, btn.dataset.name);
            } else {
                console.log('[Phase 4] Browser folder play:', btn.dataset.path);
            }
        });
    });
}

// ── Individual row renderers ─────────────────────────────────

function renderFolderRow(entry, isSearch) {
    const name = escHtml(entry.name);
    const path = escHtml(entry.path);
    // In search mode, show the full path as a hint
    const hint = isSearch
        ? `<span class="file-meta">${escHtml(entry.parent_path)}</span>`
        : `<span class="file-meta"></span>`;

    return `
    <div class="file-row folder-row">
      <span class="file-icon">📁</span>
      <a href="#" class="file-name folder-name-link" data-path="${path}">${name}</a>
      ${hint}
      <div class="file-actions">
        <button class="btn-secondary browser-folder-btn" data-path="${path}" data-name="${name}" title="Play folder in browser">▶ Browser</button>
        <button class="btn-primary sonos-folder-btn" data-path="${path}" data-name="${name}" title="Play folder on Sonos">▶ Sonos</button>
      </div>
    </div>`;
}

function renderFileRow(entry) {
    const name  = escHtml(entry.name);
    const path  = escHtml(entry.path);
    const ext   = (entry.extension || '').toLowerCase();
    const size  = entry.size  ? formatBytes(entry.size)  : '';
    const date  = entry.modified ? formatDate(entry.modified) : '';
    const meta  = [size, date].filter(Boolean).join(' · ');
    const parent = escHtml(entry.parent_path || '');

    return `
    <div class="file-row file-row-music">
      <span class="file-icon ext-badge ext-${ext}">${ext.toUpperCase() || '?'}</span>
      <span class="file-name" title="${escHtml(entry.parent_path + '/' + entry.name)}">${name}</span>
      <span class="file-meta">${meta}</span>
      <div class="file-actions">
        <button class="btn-secondary browser-play-btn" data-path="${path}" data-name="${name}">▶ Browser</button>
        <button class="btn-primary sonos-play-btn"    data-path="${path}" data-name="${name}">▶ Sonos</button>
      </div>
    </div>`;
}

// ── Search ───────────────────────────────────────────────────

function initSearch() {
    const input = document.getElementById('search-input');
    if (!input) return;

    let searchTimer = null;

    input.addEventListener('input', () => {
        clearTimeout(searchTimer);
        const q = input.value.trim();
        if (!q) {
            // Clear search: go back to current directory
            exitSearch();
            return;
        }
        searchTimer = setTimeout(() => runSearch(q), 300);  // debounce 300ms
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            input.value = '';
            exitSearch();
        }
    });

    // Re-run search when filter type changes
    document.querySelectorAll('[name="search-type"]').forEach(radio => {
        radio.addEventListener('change', () => {
            const q = input.value.trim();
            if (q) runSearch(q);
        });
    });
}

async function runSearch(q) {
    isSearchMode = true;
    showFileList();
    setFileListLoading();
    renderBreadcrumb('/');  // will show "Search Results" when isSearchMode=true

    const type = document.querySelector('[name="search-type"]:checked')?.value || 'all';

    try {
        const res = await fetch(
            `/api/files/search?q=${encodeURIComponent(q)}&type=${encodeURIComponent(type)}`
        );
        const data = await res.json();
        renderFileList(data.entries, true);  // isSearch=true → show parent path hints
    } catch (err) {
        document.getElementById('file-list').innerHTML =
            '<div class="loading-row error-row">Search error</div>';
    }
}

function exitSearch() {
    isSearchMode = false;
    loadBrowser(currentBrowserPath);
}

// ── Utility helpers ──────────────────────────────────────────

function escHtml(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatBytes(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
    return `${(bytes / 1073741824).toFixed(2)} GB`;
}

function formatDate(isoStr) {
    if (!isoStr) return '';
    try {
        return new Date(isoStr).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
        return '';
    }
}

// Expose loadBrowser globally so Phase 2's pollIndexStatus can call it
window.loadBrowser = loadBrowser;
```

---

### CSS additions to `static/style.css`

Append these rules to the existing `style.css`:

```css
/* ============================================================
   Phase 3 additions
   ============================================================ */

/* Loading / empty rows inside file-list */
.loading-row {
  padding: 20px 16px;
  color: var(--text-muted);
  font-size: 0.88rem;
  text-align: center;
}
.muted-row  { color: var(--text-muted); }
.error-row  { color: var(--danger); }

/* Folder name is a link */
.folder-row .file-name {
  color: var(--text-primary);
  font-weight: 500;
  text-decoration: none;
}
.folder-row .file-name:hover { color: var(--accent); }

/* Search result parent-path hint */
.file-meta.path-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-style: italic;
}

/* Slightly dimmer ext badges for less common formats */
.ext-ogg  { background: rgba(200,100,255,0.2); color: #cc66ff; }
.ext-aiff,
.ext-aif  { background: rgba(255,160,50,0.2);  color: #ffa032; }
```

---

### HTML changes to `templates/index.html`

The existing HTML shell from Phase 1 already has all required elements. No structural changes needed. However, add the following CSS class to `#browser-area` to scope it correctly if not already present — verify these IDs exist exactly:

- `#empty-state` — shown when no index
- `#breadcrumb` — shown when browsing (hidden initially)
- `#file-list` — shown when browsing (hidden initially)
- `#search-input` — the search text input
- `[name="search-type"]` — radio buttons with values `all`, `files`, `folders`
- `#indexing-banner` — the in-progress banner
- `#banner-count` — entry count inside banner

If any of these IDs are missing, add them now. They must match exactly.

---

## API Endpoints (Phase 3)

| Method | Path | Query Params | Description |
|--------|------|-------------|-------------|
| `GET` | `/api/files/browse` | `path=/` | List entries in a directory |
| `GET` | `/api/files/search` | `q=text&type=all\|files\|folders` | Search by name |
| `GET` | `/api/files/folder-files` | `path=/Rock` | All music files in folder (recursive) |
| `GET` | `/api/files/index-check` | — | Whether any entries are indexed |

### Example Response — `/api/files/browse?path=/Rock`
```json
{
  "path": "/Rock",
  "entries": [
    {
      "id": 12,
      "path": "/Rock/Classic Rock",
      "name": "Classic Rock",
      "parent_path": "/Rock",
      "is_directory": true,
      "size": null,
      "modified": null,
      "extension": null
    },
    {
      "id": 45,
      "path": "/Rock/Thunderstruck.mp3",
      "name": "Thunderstruck.mp3",
      "parent_path": "/Rock",
      "is_directory": false,
      "size": 7340032,
      "modified": "2023-11-10T14:22:00+00:00",
      "extension": "mp3"
    }
  ]
}
```

### Example Response — `/api/files/search?q=thunder&type=files`
```json
{
  "query": "thunder",
  "type": "files",
  "entries": [
    {
      "path": "/Rock/Thunderstruck.mp3",
      "name": "Thunderstruck.mp3",
      "parent_path": "/Rock",
      "is_directory": false,
      "size": 7340032,
      "modified": "2023-11-10T14:22:00+00:00",
      "extension": "mp3"
    }
  ]
}
```

---

## Validation Steps

1. **Run the server:** `./app.sh` — no import errors.

2. **With entries already in DB** (from Phase 2 indexing), open `http://localhost:8000`.
   - Browser tab should automatically load the root directory listing.
   - You should see folders (📁) and music files (with extension badges) in the list.
   - Folder names should be clickable links.

3. **Navigate into a folder:**
   - Click a folder name — list updates, breadcrumb shows the path.
   - Click "Home" in breadcrumb — returns to root.
   - Click intermediate breadcrumb segments — navigates correctly.

4. **File rows:**
   - Music files show the extension badge (MP3, FLAC, etc.) in colour.
   - File size and date are shown in the meta column.
   - "▶ Browser" (secondary/outline) and "▶ Sonos" (primary/green) buttons are present.
   - Clicking them logs to console (Phase 4 wires them up).

5. **Folder rows:**
   - Folders show "▶ Browser" and "▶ Sonos" buttons too.
   - Clicking them logs to console.

6. **Search:**
   - Type into the search box — results appear after 300ms debounce.
   - Breadcrumb shows "Search Results".
   - Try each filter: All / Files / Folders.
   - Parent folder path is shown as a hint on each result row.
   - Press Escape or clear the input — returns to the current directory.
   - Try a query that returns no results — "No items found" message shown.

7. **Empty state:**
   - Delete all entries: `sqlite3 sonosweb.db "DELETE FROM entries;"`
   - Refresh page — empty state panel shows with link to Settings.

8. **API directly:**
   ```bash
   curl "http://localhost:8000/api/files/browse?path=/"
   curl "http://localhost:8000/api/files/search?q=rock&type=folders"
   curl "http://localhost:8000/api/files/folder-files?path=/Rock"
   curl "http://localhost:8000/api/files/index-check"
   ```

9. **Index-then-browse flow:**
   - Go to Settings, click "Re-index Now".
   - Indexing banner appears on Browser tab with spinner and count.
   - After completion, browser auto-refreshes root directory.

---

## Notes & Gotchas

- **`COLLATE NOCASE`** in SQLite is used for case-insensitive name comparison. It works correctly for ASCII characters. For non-ASCII filenames (accented characters, Cyrillic, etc.), results will still be case-insensitive for the ASCII portions; full Unicode case folding is not supported in SQLite without extensions. This is acceptable for most music libraries.

- **Search debounce:** The 300ms timer in `initSearch()` prevents hammering the API on every keystroke. Don't remove it.

- **Folder-files endpoint** fetches all music files under a path recursively by combining an exact `parent_path` match (for direct children) and a `path LIKE '/folder/%'` pattern (for all descendants). This intentionally returns all descendants, not just immediate children, to support queuing a whole album or artist folder.

- **`window.loadBrowser = loadBrowser`** at the bottom of the new JS block makes the function accessible to the Phase 2 code in `pollIndexStatus` which calls `window.loadBrowser('/')` after indexing completes. Do not remove this line.

- **`window.playInBrowser`, `window.playOnSonos`, etc.** are checked with `if (window.xxx)` before calling. Phase 4 will define these on `window`, and the existing click handlers will automatically start using them without any changes to Phase 3 code.

- **Folder play buttons on search results:** Folders in search results show both play buttons, which call `playFolderOnSonos(path)` / `playFolderInBrowser(path)`. Phase 4 uses `/api/files/folder-files?path=...` to get all the files in that folder before queuing them — this works even when the folder was reached via search rather than direct navigation.

- **Path encoding:** All `path` values passed to `fetch()` calls use `encodeURIComponent()`. Do not skip this — paths with spaces, ampersands, or non-ASCII characters will break without it.

- **File list scroll vs fixed elements:** When the playbar is visible (Phase 4), it sits below the navbar and pushes the content down. The JS in Phase 4 will add/remove the `playbar-visible` class on `.main-content` to handle this padding automatically. No changes needed here for that.

- **Re-check IDs in index.html:** The JS code references `#empty-state`, `#breadcrumb`, `#file-list`, `#search-input`, etc. by exact ID. If Phase 1's HTML used slightly different IDs, reconcile them now before running Phase 4.
