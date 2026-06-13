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
