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
