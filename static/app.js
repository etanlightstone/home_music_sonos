/* ============================================================
   SonosWeb — app.js
   Phase 1: Tab switching + Settings CRUD
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    loadSettings();
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);

    // Auto-update port when server type changes
    document.getElementById('server_type').addEventListener('change', (e) => {
        const portInput = document.getElementById('server_port');
        if (portInput.value === '22' || portInput.value === '21' || portInput.value === '') {
            portInput.value = e.target.value === 'sftp' ? '22' : '21';
        }
    });

    // Index management
    document.getElementById('reindex-btn')?.addEventListener('click', startIndexing);
    document.getElementById('interrupt-settings-btn')?.addEventListener('click', interruptIndexing);
    document.getElementById('banner-interrupt-btn')?.addEventListener('click', interruptIndexing);

    // Check index status on load
    fetch('/api/index/status').then(r => r.json()).then(status => {
        updateIndexUI(status);
        if (status.is_running) startIndexPoll();
    }).catch(() => {});
});

/* ── Tab switching ─────────────────────────────────────────── */
function initTabs() {
    document.querySelectorAll('.tab-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            switchTab(link.dataset.tab);
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.add('hidden'));
    document.querySelectorAll('.tab-link').forEach(t => t.classList.remove('active'));
    document.getElementById('tab-' + tabId)?.classList.remove('hidden');
    document.querySelectorAll(`.tab-link[data-tab="${tabId}"]`).forEach(l => l.classList.add('active'));
}

/* ── Settings ──────────────────────────────────────────────── */
async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        const data = await res.json();
        Object.entries(data).forEach(([key, value]) => {
            const el = document.querySelector(`[name="${key}"]`);
            if (el) el.value = value ?? '';
        });
    } catch (err) {
        console.error('Failed to load settings:', err);
    }
}

async function saveSettings() {
    const form = document.getElementById('settings-form');
    const data = {};
    new FormData(form).forEach((v, k) => { data[k] = v; });
    try {
        const res = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (res.ok) {
            showToast('Settings saved', 'success');
        } else {
            showToast('Save failed', 'error');
        }
    } catch (err) {
        showToast('Save failed: ' + err.message, 'error');
    }
}

/* ── Toast notifications ───────────────────────────────────── */
function showToast(msg, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

/* ── Index management ─────────────────────────────────────── */

let indexPollTimer = null;

async function startIndexing() {
    const res = await fetch('/api/index/start', { method: 'POST' });
    const data = await res.json();
    if (data.status === 'started' || data.status === 'already_running') {
        startIndexPoll();
    } else {
        showToast('Failed to start indexing', 'error');
    }
}

async function interruptIndexing() {
    await fetch('/api/index/interrupt', { method: 'POST' });
    stopIndexPoll();
    updateIndexUI({ is_running: false, was_interrupted: true, processed_entries: 0, completed_at: null });
    showToast('Indexing interrupted', 'error');
}

function startIndexPoll() {
    if (indexPollTimer) clearInterval(indexPollTimer);
    pollIndexStatus();  // immediate
    indexPollTimer = setInterval(pollIndexStatus, 2000);
}

function stopIndexPoll() {
    if (indexPollTimer) { clearInterval(indexPollTimer); indexPollTimer = null; }
}

async function pollIndexStatus() {
    try {
        const res = await fetch('/api/index/status');
        const status = await res.json();
        updateIndexUI(status);
        if (!status.is_running) {
            stopIndexPoll();
            if (status.completed_at && window.loadBrowser) {
                loadBrowser('/');  // refresh browser (Phase 3 will define this)
            }
        }
    } catch (err) {
        console.error('Index poll error:', err);
        stopIndexPoll();
    }
}

function updateIndexUI(status) {
    const isRunning = status.is_running;
    const count     = status.processed_entries ?? 0;
    const lastTime  = status.completed_at
        ? new Date(status.completed_at).toLocaleString()
        : 'Never';

    // Browser tab banner
    document.getElementById('indexing-banner')?.classList.toggle('hidden', !isRunning);
    const bannerCount = document.getElementById('banner-count');
    if (bannerCount) bannerCount.textContent = count;

    // Settings tab progress
    document.getElementById('settings-index-progress')?.classList.toggle('hidden', !isRunning);
    const settingsCount = document.getElementById('settings-index-count');
    if (settingsCount) settingsCount.textContent = count;

    // Last indexed text
    const lastEl = document.getElementById('last-indexed');
    if (lastEl) lastEl.textContent = isRunning ? 'In progress...' : lastTime;

    // Interrupt buttons
    document.getElementById('banner-interrupt-btn')?.classList.toggle('hidden', !isRunning);
    document.getElementById('interrupt-settings-btn')?.classList.toggle('hidden', !isRunning);
    document.getElementById('reindex-btn')?.classList.toggle('hidden', isRunning);
}

/* ============================================================
   Phase 3 — Browser navigation & search
   ============================================================ */

// ── State ───────────────────────────────────────────────────
let currentBrowserPath = '/';
let isSearchMode = false;

// ── Boot: check index on page load ──────────────────────────
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
    let html = '<a href="#" class="crumb-link crumb-home" data-path="/"><svg class="crumb-home-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3L2 12h3v8h6v-6h2v6h6v-8h3L12 3z"/></svg> Home</a>';

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

    let html = '';

    if (!isSearch && currentBrowserPath) {
        html = `
        <div class="play-all-bar">
            <span class="play-all-label">Play all</span>
            <button class="btn-secondary play-all-browser-btn" data-path="${currentBrowserPath}" title="Play all tracks in browser">▶ Browser</button>
            <button class="btn-primary play-all-sonos-btn" data-path="${currentBrowserPath}" title="Play all tracks on Sonos">▶ Sonos</button>
        </div>`;
    }

    const rows = entries.map(entry =>
        entry.is_directory
            ? renderFolderRow(entry, isSearch)
            : renderFileRow(entry)
    );
    list.innerHTML = html + rows.join('');

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

    list.querySelectorAll('.play-all-browser-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.playFolderInBrowser) {
                const folderName = btn.dataset.path.split('/').pop() || 'this folder';
                playFolderInBrowser(btn.dataset.path, folderName);
            } else {
                console.log('[Phase 4] Play all browser:', btn.dataset.path);
            }
        });
    });

    // Clicking anywhere on a file row triggers Sonos play
    list.querySelectorAll('.file-row-music').forEach(row => {
        row.addEventListener('click', (e) => {
            if (e.target.closest('.file-actions, .folder-name-link')) return;
            const sonosBtn = row.querySelector('.sonos-play-btn');
            if (sonosBtn) sonosBtn.click();
        });
    });

    list.querySelectorAll('.play-all-sonos-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (window.playFolderOnSonos) {
                const folderName = btn.dataset.path.split('/').pop() || 'this folder';
                playFolderOnSonos(btn.dataset.path, folderName);
            } else {
                console.log('[Phase 4] Play all Sonos:', btn.dataset.path);
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
    const clearBtn = document.getElementById('clear-search-btn');
    if (!input) return;

    let searchTimer = null;

    function updateClearBtn() {
        if (clearBtn) {
            clearBtn.classList.toggle('hidden', !input.value.trim());
        }
    }

    input.addEventListener('input', () => {
        clearTimeout(searchTimer);
        updateClearBtn();
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
            updateClearBtn();
            exitSearch();
        }
    });

    clearBtn?.addEventListener('click', () => {
        input.value = '';
        updateClearBtn();
        exitSearch();
        input.focus();
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

/* ============================================================
   Phase 4 — Playback engine (Sonos + in-browser)
   ============================================================ */

// ── Shared playback state ────────────────────────────────────
const playback = {
    mode:            null,
    currentTitle:    '',
    isPlaying:       false,
    isPaused:        false,
    browserPlaylist: [],
    browserIndex:    -1,
    sonosPoller:     null,
    sonosQueue:      [],
    volume:          50,
};

// ── DOM refs ─────────────────────────────────────────────────
const audioEl       = document.getElementById('audio-player');
const playbar       = document.getElementById('playbar');
const btnPrev       = document.getElementById('btn-prev');
const btnPlayPause  = document.getElementById('btn-playpause');
const btnNext       = document.getElementById('btn-next');
const nowLabel      = document.getElementById('now-playing-label');
const nowMode       = document.getElementById('now-playing-mode');
const mainContent   = document.querySelector('.main-content');

// Volume DOM refs
const volumeIcon    = document.getElementById('volume-icon');
const volumeSlider  = document.getElementById('volume-slider');
const volumeValue   = document.getElementById('volume-value');
const epVolumeIcon  = document.getElementById('ep-volume-icon');
const epVolumeSlider= document.getElementById('ep-volume-slider');
const epVolumeValue = document.getElementById('ep-volume-value');

// ── Initialise controls bar ──────────────────────────────────
document.addEventListener('DOMContentLoaded', initPlaybackControls);

function initPlaybackControls() {
    btnPrev?.addEventListener('click',      onPrev);
    btnPlayPause?.addEventListener('click', onPlayPause);
    btnNext?.addEventListener('click',      onNext);

    if (audioEl) {
        audioEl.addEventListener('ended',   onBrowserTrackEnded);
        audioEl.addEventListener('play',    () => setPlayPauseBtn(true));
        audioEl.addEventListener('pause',   () => setPlayPauseBtn(false));
        audioEl.addEventListener('error',   (e) => console.error('[Audio]', e));
    }

    // Volume sliders
    volumeSlider?.addEventListener('input', onVolumeInput);
    epVolumeSlider?.addEventListener('input', onVolumeInput);

    // Check if Sonos is already playing (handles browser refresh recovery)
    checkSonosOnLoad();
}

async function checkSonosOnLoad() {
    try {
        const res  = await fetch('/api/sonos/state');
        const data = await res.json();
        const state = data.state || 'UNKNOWN';
        const isPlaying = state === 'PLAYING';
        const isPaused = state === 'PAUSED_PLAYBACK';

        if (isPlaying || isPaused) {
            const sonosTitle = data.title || 'Now Playing';
            const sonosUri   = data.uri || '';

            let title = sonosTitle;
            if (playback.sonosQueue.length > 0 && sonosUri) {
                const uriIdx = playback.sonosQueue.findIndex(q => q.uri && sonosUri.includes(q.uri));
                if (uriIdx !== -1) title = playback.sonosQueue[uriIdx].title;
            }

            playback.mode = 'sonos';
            playback.isPaused = isPaused;
            updateNowPlaying(title, 'sonos');
            setPlayPauseBtn(isPlaying);
            if (data.volume !== undefined) setVolumeUI(data.volume);
            startSonosPoller();
        }
    } catch (err) {
        // Sonos unavailable or not configured — no-op
    }
}

// ── Show/hide playbar ────────────────────────────────────────
function showPlaybar() {
    playbar?.classList.remove('hidden');
    mainContent?.classList.add('playbar-visible');
}

function updateNowPlaying(title, mode) {
    playback.currentTitle = title;
    playback.mode = mode;
    showPlaybar();
    if (nowLabel) nowLabel.textContent = title || 'Playing…';
    if (nowMode) {
        nowMode.textContent   = mode === 'sonos' ? 'Sonos' : 'Browser';
        nowMode.className     = `mode-badge ${mode}`;
    }
    if (epBottomTrackName) epBottomTrackName.textContent = title || '—';
}

function setPlayPauseBtn(isPlaying) {
    playback.isPlaying = isPlaying;
    if (btnPlayPause) {
        btnPlayPause.querySelector('.icon-pause').style.display = isPlaying ? '' : 'none';
        btnPlayPause.querySelector('.icon-play').style.display = isPlaying ? 'none' : '';
    }
    syncEpPlayPauseIcon();
}

// ── Controls bar button handlers ────────────────────────────

function onPlayPause() {
    if (playback.mode === 'browser') {
        if (!audioEl) return;
        if (audioEl.paused) {
            audioEl.play();
        } else {
            audioEl.pause();
        }
    } else if (playback.mode === 'sonos') {
        if (playback.isPaused) {
            fetch('/api/sonos/resume', { method: 'POST' }).then(() => {
                playback.isPaused = false;
                setPlayPauseBtn(true);
            });
        } else {
            fetch('/api/sonos/pause', { method: 'POST' }).then(() => {
                playback.isPaused = true;
                setPlayPauseBtn(false);
            });
        }
    }
}

function onNext() {
    if (playback.mode === 'browser') {
        advanceBrowserPlaylist(1);
    } else if (playback.mode === 'sonos') {
        fetch('/api/sonos/next', { method: 'POST' })
            .then(r => r.json())
            .then(() => setTimeout(syncSonosState, 500));
    }
}

function onPrev() {
    if (playback.mode === 'browser') {
        advanceBrowserPlaylist(-1);
    } else if (playback.mode === 'sonos') {
        fetch('/api/sonos/previous', { method: 'POST' })
            .then(r => r.json())
            .then(() => setTimeout(syncSonosState, 500));
    }
}

// ── Volume control ───────────────────────────────────────────

function setVolumeUI(vol) {
    playback.volume = vol;
    if (volumeSlider) volumeSlider.value = vol;
    if (epVolumeSlider) epVolumeSlider.value = vol;
    if (volumeValue) volumeValue.textContent = vol;
    if (epVolumeValue) epVolumeValue.textContent = vol;
    if (volumeIcon) {
        if (vol === 0) volumeIcon.textContent = '🔇';
        else if (vol < 30) volumeIcon.textContent = '🔈';
        else if (vol < 70) volumeIcon.textContent = '🔉';
        else volumeIcon.textContent = '🔊';
    }
    if (epVolumeIcon) {
        if (vol === 0) epVolumeIcon.textContent = '🔇';
        else if (vol < 30) epVolumeIcon.textContent = '🔈';
        else if (vol < 70) epVolumeIcon.textContent = '🔉';
        else epVolumeIcon.textContent = '🔊';
    }
    if (epBottomVolumeIcon) {
        if (vol === 0) epBottomVolumeIcon.textContent = '🔇';
        else if (vol < 30) epBottomVolumeIcon.textContent = '🔈';
        else if (vol < 70) epBottomVolumeIcon.textContent = '🔉';
        else epBottomVolumeIcon.textContent = '🔊';
    }
    if (epBottomVolumeValue) epBottomVolumeValue.textContent = vol;
}

function onVolumeInput(e) {
    const vol = parseInt(e.target.value, 10);
    setVolumeUI(vol);
    if (playback.mode === 'sonos') {
        fetch('/api/sonos/set-volume', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ volume: vol }),
        }).catch(err => console.error('[Volume]', err));
    }
}

// ── IN-BROWSER PLAYBACK ──────────────────────────────────────

window.playInBrowser = function(relPath, name) {
    const proxyUrl = proxyUrlFromPath(relPath);
    playback.browserPlaylist = [{ path: relPath, name, proxyUrl }];
    playback.browserIndex    = 0;
    _startBrowserTrack(0);
};

window.playFolderInBrowser = async function(folderPath, folderName) {
    try {
        const res  = await fetch(`/api/files/folder-files?path=${encodeURIComponent(folderPath)}`);
        const data = await res.json();
        const files = data.files || [];
        if (!files.length) { showToast('No music files found in folder', 'error'); return; }
        playback.browserPlaylist = files.map(f => ({
            path:     f.path,
            name:     f.name,
            proxyUrl: proxyUrlFromPath(f.path),
        }));
        playback.browserIndex = 0;
        _startBrowserTrack(0);
        showToast(`Playing ${files.length} tracks from "${folderName || folderPath}"`, 'success');
    } catch (err) {
        showToast('Failed to load folder: ' + err.message, 'error');
    }
};

function _startBrowserTrack(index) {
    if (!audioEl) return;
    const track = playback.browserPlaylist[index];
    if (!track) return;
    playback.browserIndex = index;
    audioEl.src = track.proxyUrl;
    audioEl.play().catch(err => console.error('[Audio] play error:', err));
    updateNowPlaying(track.name, 'browser');
    stopSonosPoller();
    playback.sonosQueue = [];
}

function onBrowserTrackEnded() {
    const nextIdx = playback.browserIndex + 1;
    if (nextIdx < playback.browserPlaylist.length) {
        _startBrowserTrack(nextIdx);
    } else {
        setPlayPauseBtn(false);
        if (nowLabel) nowLabel.textContent = 'Playback finished';
    }
}

function advanceBrowserPlaylist(delta) {
    const nextIdx = playback.browserIndex + delta;
    if (nextIdx >= 0 && nextIdx < playback.browserPlaylist.length) {
        _startBrowserTrack(nextIdx);
    }
}

// ── SONOS PLAYBACK ───────────────────────────────────────────

window.playOnSonos = async function(relPath, name) {
    try {
        const res  = await fetch('/api/sonos/play-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: relPath, name }),
        });
        const data = await res.json();
        if (data.status === 'error') {
            showToast('Sonos error: ' + data.message, 'error');
            return;
        }
        if (audioEl) { audioEl.pause(); audioEl.src = ''; }
        playback.isPaused = false;
        playback.sonosQueue = [];
        updateNowPlaying(name || relPath.split('/').pop(), 'sonos');
        setPlayPauseBtn(true);
        startSonosPoller();
        showToast(`Playing on Sonos: ${name}`, 'success');
        // Check state after 1s to catch immediate failures (e.g. Sonos can't reach proxy URL)
        setTimeout(syncSonosState, 1000);
    } catch (err) {
        showToast('Sonos play failed: ' + err.message, 'error');
    }
};

window.playFolderOnSonos = async function(folderPath, folderName) {
    showToast(`Loading "${folderName || folderPath}" into Sonos queue…`, 'success');
    try {
        const res  = await fetch('/api/sonos/play-folder', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: folderPath }),
        });
        const data = await res.json();
        if (data.status === 'error') {
            showToast('Sonos error: ' + data.message, 'error');
            return;
        }
        if (audioEl) { audioEl.pause(); audioEl.src = ''; }
        playback.isPaused = false;
        const firstTitle = data.first_title || folderName;
        playback.sonosQueue = (data.titles || []).map((title, i) => ({
            title,
            uri: data.uris && data.uris[i] ? data.uris[i] : null,
        }));
        updateNowPlaying(firstTitle, 'sonos');
        setPlayPauseBtn(true);
        startSonosPoller();
        showToast(`${data.track_count} tracks queued on Sonos`, 'success');
        setTimeout(syncSonosState, 1000);
    } catch (err) {
        showToast('Sonos folder play failed: ' + err.message, 'error');
    }
};

// ── Sonos state polling ──────────────────────────────────────

function startSonosPoller() {
    stopSonosPoller();
    playback.sonosPoller = setInterval(syncSonosState, 3000);
}

function stopSonosPoller() {
    if (playback.sonosPoller) {
        clearInterval(playback.sonosPoller);
        playback.sonosPoller = null;
    }
}

async function syncSonosState() {
    if (playback.mode !== 'sonos') { stopSonosPoller(); return; }
    try {
        const res  = await fetch('/api/sonos/state');
        const data = await res.json();
        const state    = data.state || 'UNKNOWN';
        const sonosTitle = data.title || '';
        const sonosUri   = data.uri || '';
        const tracknum   = data.tracknum || '';
        const isPlaying  = state === 'PLAYING';
        const isStopped  = state === 'STOPPED' || state === 'NO_MEDIA_PRESENT';
        const isFailed   = state === 'PLAYBACK_FAILED';

        let title = sonosTitle;

        if (playback.sonosQueue.length > 0) {
            // Fallback 1: match by URI
            if (sonosUri) {
                const uriIdx = playback.sonosQueue.findIndex(q => q.uri && sonosUri.includes(q.uri));
                if (uriIdx !== -1) {
                    title = playback.sonosQueue[uriIdx].title;
                }
            }

            // Fallback 2: use tracknum if URI match failed and title is missing/wrong
            if (!title && tracknum) {
                const idx = parseInt(tracknum, 10) - 1;
                if (idx >= 0 && idx < playback.sonosQueue.length) {
                    title = playback.sonosQueue[idx].title;
                }
            }
        } else if (!sonosTitle) {
            title = playback.currentTitle;
        }

        if (title && title !== playback.currentTitle) {
            updateNowPlaying(title, 'sonos');
        }
        playback.isPaused = (state === 'PAUSED_PLAYBACK');
        setPlayPauseBtn(isPlaying);

        if (data.volume !== undefined && data.volume !== playback.volume) {
            setVolumeUI(data.volume);
        }

        if (isFailed) {
            stopSonosPoller();
            showToast('Sonos failed to play — check that the speaker can reach the web server URL', 'error');
        } else if (isStopped) {
            stopSonosPoller();
        }
    } catch (err) {
        // Network error — keep polling, Sonos may be momentarily busy
    }
}

// ── Helper: build proxy URL from relative file path ──────────
function proxyUrlFromPath(relPath) {
    const clean = relPath.replace(/^\/+/, '');
    return `/api/proxy/${clean}`;
}

/* ============================================================
   PHASE 5 — Expanded Player & Microphone Spectrum Visualizer
   ============================================================ */

// ── Visualizer state ─────────────────────────────────────────
const viz = {
    audioCtx:    null,
    analyser:    null,
    stream:      null,
    bufferLen:   0,
    dataArray:   null,
    animFrameId: null,
    binsPerBar:  4,
    ready:       false,
};

let epCanvas = null;
let epCtx    = null;

const expandedPlayer   = document.getElementById('expanded-player');
const expandBtn        = document.getElementById('expand-player-btn');
const epCloseBtn       = document.getElementById('ep-close-btn');
const epTrackName      = document.getElementById('ep-track-name');
const epModeBadge      = document.getElementById('ep-mode-badge');
const epBottomTrackName = document.getElementById('ep-bottom-track-name');
const epBottomVolumeIcon = document.getElementById('ep-bottom-volume-icon');
const epBottomVolumeValue = document.getElementById('ep-bottom-volume-value');
const epBtnPrev        = document.getElementById('ep-btn-prev');
const epBtnPlayPause   = document.getElementById('ep-btn-playpause');
const epBtnNext        = document.getElementById('ep-btn-next');
const epVizUnavail     = document.getElementById('ep-viz-unavail');
const epVizWaiting     = document.getElementById('ep-viz-waiting');

document.addEventListener('DOMContentLoaded', initExpandedPlayer);

function initExpandedPlayer() {
    epCanvas = document.getElementById('ep-canvas');
    epCtx    = epCanvas ? epCanvas.getContext('2d') : null;

    expandBtn?.addEventListener('click',   openExpandedPlayer);
    epCloseBtn?.addEventListener('click',  closeExpandedPlayer);

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && expandedPlayer?.classList.contains('ep-open')) {
            closeExpandedPlayer();
        }
    });

    epBtnPrev?.addEventListener('click',      onPrev);
    epBtnNext?.addEventListener('click',      onNext);
    epBtnPlayPause?.addEventListener('click', onPlayPause);

    document.querySelectorAll('.ep-grain-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            viz.binsPerBar = Number(btn.dataset.bins);
            document.querySelectorAll('.ep-grain-btn').forEach(b =>
                b.classList.remove('ep-grain-active'));
            btn.classList.add('ep-grain-active');
        });
    });

    window.addEventListener('resize', syncCanvasSize);
}

function openExpandedPlayer() {
    if (!expandedPlayer) return;

    syncEpTrackInfo();
    if (playback.mode === 'sonos' && playback.volume !== undefined) {
        setVolumeUI(playback.volume);
    }

    expandedPlayer.classList.add('ep-open');
    expandedPlayer.setAttribute('aria-hidden', 'false');

    expandBtn.style.display = 'none';

    syncCanvasSize();

    startVisualizer();
}

function closeExpandedPlayer() {
    if (!expandedPlayer) return;
    expandedPlayer.classList.remove('ep-open');
    expandedPlayer.setAttribute('aria-hidden', 'true');

    expandBtn.style.display = '';

    stopDrawLoop();
}

function syncEpTrackInfo() {
    if (epTrackName) {
        epTrackName.textContent = playback.currentTitle || '—';
    }
    if (epBottomTrackName) {
        epBottomTrackName.textContent = playback.currentTitle || '—';
    }
    if (epModeBadge && playback.mode) {
        epModeBadge.textContent = playback.mode === 'sonos' ? 'Sonos' : 'Browser';
        epModeBadge.className   = `ep-mode-badge ${playback.mode}`;
    }
}

(function patchUpdateNowPlaying() {
    const _original = window.updateNowPlaying || updateNowPlaying;
    const patched = function(title, mode) {
        _original(title, mode);
        if (expandedPlayer?.classList.contains('ep-open')) {
            syncEpTrackInfo();
        }
        syncEpPlayPauseIcon();
    };
    window._patchedUpdateNowPlaying = patched;
})();



function syncEpPlayPauseIcon() {
    if (epBtnPlayPause) {
        epBtnPlayPause.querySelector('.ep-icon-pause').style.display = playback.isPlaying ? '' : 'none';
        epBtnPlayPause.querySelector('.ep-icon-play').style.display = playback.isPlaying ? 'none' : '';
    }
}

function syncCanvasSize() {
    if (!epCanvas) return;
    const wrap = document.getElementById('ep-viz-wrap');
    if (!wrap) return;
    const w = wrap.offsetWidth;
    const h = wrap.offsetHeight;
    if (w > 0 && h > 0) {
        epCanvas.width  = w;
        epCanvas.height = h;
    }
}

async function startVisualizer() {
    epVizWaiting?.classList.remove('hidden');
    epVizUnavail?.classList.add('hidden');

    if (!viz.ready) {
        try {
            viz.stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            viz.audioCtx = new (window.AudioContext || window.webkitAudioContext)();

            const source  = viz.audioCtx.createMediaStreamSource(viz.stream);

            viz.analyser  = viz.audioCtx.createAnalyser();
            viz.analyser.fftSize               = 2048;
            viz.analyser.smoothingTimeConstant = 0.8;

            source.connect(viz.analyser);

            viz.bufferLen  = viz.analyser.frequencyBinCount;
            viz.dataArray  = new Uint8Array(viz.bufferLen);
            viz.ready      = true;

        } catch (err) {
            console.error('[Visualizer] Mic error:', err);
            epVizWaiting?.classList.add('hidden');
            epVizUnavail?.classList.remove('hidden');
            return;
        }
    } else if (viz.audioCtx?.state === 'suspended') {
        await viz.audioCtx.resume();
    }

    epVizWaiting?.classList.add('hidden');

    startDrawLoop();
}

function startDrawLoop() {
    stopDrawLoop();
    drawFrame();
}

function stopDrawLoop() {
    if (viz.animFrameId !== null) {
        cancelAnimationFrame(viz.animFrameId);
        viz.animFrameId = null;
    }
}

function drawFrame() {
    if (!viz.ready || !viz.analyser || !epCtx || !epCanvas) return;

    viz.analyser.getByteFrequencyData(viz.dataArray);
    drawSpectrumBars(viz.dataArray, viz.bufferLen);

    viz.animFrameId = requestAnimationFrame(drawFrame);
}

function getVisibleBinCount(bufferLength) {
    const singleBarWidth = epCanvas.width / bufferLength * 2.5;
    return Math.floor(epCanvas.width / (singleBarWidth + 1));
}

function drawSpectrumBars(dataArray, bufferLength) {
    const visibleBins = getVisibleBinCount(bufferLength);
    const barCount    = Math.ceil(visibleBins / viz.binsPerBar);
    const barWidth    = (epCanvas.width - barCount) / barCount;

    epCtx.fillStyle = '#000';
    epCtx.fillRect(0, 0, epCanvas.width, epCanvas.height);

    for (let bar = 0; bar < barCount; bar++) {
        const start = bar * viz.binsPerBar;
        const end   = Math.min(start + viz.binsPerBar, visibleBins);

        let peak = 0;
        for (let i = start; i < end; i++) {
            if (dataArray[i] > peak) peak = dataArray[i];
        }

        const barHeight = (peak / 255) * epCanvas.height;
        const x         = bar * (barWidth + 1);

        epCtx.fillStyle = `rgb(${peak + 50}, ${255 - peak}, 100)`;
        epCtx.fillRect(x, epCanvas.height - barHeight, Math.max(1, barWidth), barHeight);
    }
}

/* ============================================================
   SPOTIFY — Phase 1: Tab init, auth check, settings status
   ============================================================ */

document.addEventListener('DOMContentLoaded', initSpotifyTab);

async function initSpotifyTab() {
    await checkSpotifyAuth();

    // Handle redirect back from Spotify OAuth
    const params = new URLSearchParams(window.location.search);
    if (params.get('spotify_auth') === 'success') {
        showToast('Spotify connected!', 'success');
        if (params.get('tab') === 'spotify') switchTab('spotify');
        // Clean URL
        history.replaceState({}, '', '/');
    } else if (params.get('spotify_auth') === 'error') {
        showToast('Spotify auth failed. Check credentials in Settings.', 'error');
        history.replaceState({}, '', '/');
    }

    // Logout button
    document.getElementById('spotify-logout-btn')?.addEventListener('click', async () => {
        await fetch('/api/spotify/logout', { method: 'POST' });
        showToast('Spotify disconnected', 'success');
        checkSpotifyAuth();
    });
}

async function checkSpotifyAuth() {
    try {
        const res  = await fetch('/api/spotify/auth-status');
        const data = await res.json();
        const auth = data.authenticated;

        // Spotify tab content
        document.getElementById('spotify-auth-prompt')?.classList.toggle('hidden', auth);
        document.getElementById('spotify-browser')?.classList.toggle('hidden', !auth);

        // Settings tab auth state
        const badge = document.getElementById('spotify-auth-badge');
        if (badge) {
            badge.textContent = auth ? 'Connected' : 'Not connected';
            badge.className = `spotify-status-badge ${auth ? 'connected' : 'disconnected'}`;
        }
        document.getElementById('spotify-login-link')?.classList.toggle('hidden', auth);
        document.getElementById('spotify-logout-btn')?.classList.toggle('hidden', !auth);

        // Show redirect URI in auth prompt
        const uriDisplay = document.getElementById('redirect-uri-display');
        if (uriDisplay) {
            const settings = await fetch('/api/settings').then(r => r.json());
            uriDisplay.textContent = settings.spotify_redirect_uri || 'http://localhost:8000/spotify/callback';
        }

        return auth;
    } catch (err) {
        console.error('[Spotify] Auth check failed:', err);
        return false;
    }
}

// Expose so Phase 2 can call it after a fresh auth
window.checkSpotifyAuth = checkSpotifyAuth;


/* ============================================================
   SPOTIFY — Phase 2: Library browser, pin system, search
   ============================================================ */

const sp = {
    view:        'artists',
    searchScope: 'library',
    breadcrumb:  [],
    searchTimer: null,
};

document.addEventListener('DOMContentLoaded', () => {
    const browserEl = document.getElementById('spotify-browser');
    if (!browserEl) return;

    const observer = new MutationObserver(() => {
        if (!browserEl.classList.contains('hidden')) {
            initSpotifyBrowser();
            observer.disconnect();
        }
    });
    observer.observe(browserEl, { attributes: true, attributeFilter: ['class'] });

    if (!browserEl.classList.contains('hidden')) {
        initSpotifyBrowser();
    }
});

function initSpotifyBrowser() {
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

// ── Pin IDs cache ─────────────────────────────────────────────
const pinnedIds = new Set();

async function refreshPinnedIds() {
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
            rows.push(`<div class="sp-live-banner"><span class="sp-live-dot"></span>Browsing live from Spotify — pin albums to save to your library</div>`);
            const liveRes  = await fetch(`/api/spotify/artist/${encodeURIComponent(artistId)}/albums`);
            const liveData = await liveRes.json();
            const liveAlbums = liveData.albums || [];
            for (const al of liveAlbums) {
                const pinRes = await fetch(`/api/spotify/pin/check/${encodeURIComponent(al.id)}`);
                const pinData = await pinRes.json();
                rows.push(renderSpAlbumRow({...al, spotify_id: al.id, artist_id: artistId, artist_name: artistName}, pinData.pinned));
            }
        } else if (albums.length === 0) {
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
    spSetLoading();
    try {
        const res  = await fetch(`/api/spotify/pins/tracks/${encodeURIComponent(albumId)}`);
        const data = await res.json();
        let tracks = data.tracks || [];

        if (!tracks.length) {
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
        try {
            const arRes = await fetch(`/api/spotify/pins/artists`);
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

    list.querySelectorAll('.sp-artist-link').forEach(el => {
        el.addEventListener('click', e => {
            e.preventDefault();
            const id   = el.dataset.id;
            const name = el.dataset.name;
            sp.breadcrumb = [{ label: name, action: () => loadSpotifyAlbumsForArtist(id, name) }];
            loadSpotifyAlbumsForArtist(id, name);
        });
    });

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

    list.querySelectorAll('.sp-playlist-link').forEach(el => {
        el.addEventListener('click', e => {
            e.preventDefault();
            loadSpotifyPlaylistTracks(el.dataset.id, el.dataset.name);
        });
    });

    list.querySelectorAll('[data-action="pin"]').forEach(btn => {
        btn.addEventListener('click', () => toggleSpotifyPin(btn));
    });

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
