# Phase 5: Expanded Player & Spectrum Visualizer

## What This Phase Builds
- An **expand icon** (⛶) on the compact playbar that slides open a semi-fullscreen player overlay
- The overlay shows the current track name prominently, large playback controls, and a **live audio spectrum visualizer** driven by the **device microphone** via the Web Audio API
- Granularity toggle (Fine / Medium / Coarse) — **Medium is the default** (`binsPerBar = 4`), matching the provided sample code exactly
- Smooth slide-up open / slide-down close animation
- **No backend changes.** This is 100% HTML/CSS/JS additions only.

---

## Full App Context (Read Before Starting)
You are adding a feature to **SonosWeb**, a dark-themed music browser app. The backend is Python FastAPI; the frontend is vanilla HTML/CSS/JS.

**Already built and must not be broken:**
- `#playbar` — fixed bar below the navbar, hidden until something plays. Contains `#btn-prev`, `#btn-playpause`, `#btn-next`, `#now-playing-label`, `#now-playing-mode`, `#audio-player` (hidden `<audio>`).
- `static/app.js` — Phase 4 defines `playback` state object, `updateNowPlaying(title, mode)`, `onPrev()`, `onPlayPause()`, `onNext()`, `setPlayPauseBtn(bool)`, `showToast(msg, type)`.
- `static/style.css` — dark theme with CSS variables: `--bg-primary`, `--bg-secondary`, `--bg-tertiary`, `--accent`, `--border`, `--text-primary`, `--text-secondary`, `--text-muted`, `--topnav-h`, `--playbar-h`, `--radius`, `--font`.

**The mic visualizer is ambient** — it picks up what the room hears (Sonos speaker output, laptop speakers, etc.). No audio routing through the browser is needed and no Web Audio connections to the `<audio>` element are made. This is intentional and matches the provided sample code approach.

---

## Files to Modify

```
sonosweb/
├── templates/
│   └── index.html     ← MODIFY: add expand btn to playbar + overlay HTML
├── static/
│   ├── style.css      ← MODIFY: append expanded player styles
│   └── app.js         ← MODIFY: append expanded player + visualizer logic
```

No new files. No backend changes.

---

## Implementation

### 1. `templates/index.html` — Two additions

#### Addition A: Expand button inside `#playbar`

Find the existing `#playbar` div. Add the expand button as the **last child**, after the `#now-playing-mode` span:

```html
<!-- existing playbar -->
<div id="playbar" class="playbar hidden">
  <div class="playbar-controls">
    <button id="btn-prev"       class="ctrl-btn" title="Previous">⏮</button>
    <button id="btn-playpause"  class="ctrl-btn" title="Play/Pause">⏸</button>
    <button id="btn-next"       class="ctrl-btn" title="Next">⏭</button>
  </div>
  <div class="playbar-info">
    <span id="now-playing-label" class="now-playing-label">Nothing playing</span>
    <span id="now-playing-mode"  class="mode-badge"></span>
  </div>
  <audio id="audio-player" hidden></audio>

  <!-- ADD THIS: -->
  <button id="expand-player-btn" class="expand-btn" title="Expand player">
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
      <path d="M1 1h5v1.5H2.5V7H1V1zm9 0h5v6h-1.5V2.5H10V1zM1 9h1.5v4.5H7V15H1V9zm12.5 4.5H10V15h5V9h-1.5v4.5z"/>
    </svg>
  </button>
</div>
```

The SVG is a simple expand/maximize icon (four corner arrows). It renders universally and scales cleanly.

#### Addition B: Expanded player overlay

Place this **after** the `</main>` closing tag and before `<script src="/static/app.js">`:

```html
<!-- ═══════════════════════════════════════════════════════
     EXPANDED PLAYER OVERLAY
     Hidden by default. Slides up from below nav when opened.
     ═══════════════════════════════════════════════════════ -->
<div id="expanded-player" class="expanded-player" aria-hidden="true">

  <!-- Header row: track info + close -->
  <div class="ep-header">
    <div class="ep-track-info">
      <span class="ep-now-label">NOW PLAYING</span>
      <span class="ep-track-name" id="ep-track-name">—</span>
      <span class="ep-mode-badge" id="ep-mode-badge"></span>
    </div>
    <button class="ep-close-btn" id="ep-close-btn" title="Collapse player">
      <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor">
        <path d="M6 1H1v5h1.5V2.5H6V1zm4 0v1.5h3.5V6H15V1h-5zM1 10h1.5v3.5H6V15H1v-5zm12.5 3.5H10V15h5v-5h-1.5v3.5z"/>
      </svg>
    </button>
  </div>

  <!-- Spectrum visualizer -->
  <div class="ep-viz-wrap" id="ep-viz-wrap">
    <canvas id="ep-canvas"></canvas>

    <!-- Shown if mic permission denied or unavailable -->
    <div class="ep-viz-unavail hidden" id="ep-viz-unavail">
      <span class="ep-viz-unavail-icon">🎤</span>
      <span class="ep-viz-unavail-msg">Microphone unavailable</span>
      <span class="ep-viz-unavail-sub">Grant microphone permission in your browser to see the spectrum visualizer</span>
    </div>

    <!-- Shown while waiting for mic permission -->
    <div class="ep-viz-waiting" id="ep-viz-waiting">
      <span class="spinner"></span>
      <span>Waiting for microphone…</span>
    </div>
  </div>

  <!-- Granularity controls -->
  <div class="ep-granularity">
    <span class="ep-granularity-label">Bar detail</span>
    <button class="ep-grain-btn" data-bins="1">Fine</button>
    <button class="ep-grain-btn ep-grain-active" data-bins="4">Medium</button>
    <button class="ep-grain-btn" data-bins="16">Coarse</button>
  </div>

  <!-- Large playback controls -->
  <div class="ep-controls">
    <button class="ep-ctrl-btn" id="ep-btn-prev"      title="Previous">⏮</button>
    <button class="ep-ctrl-btn ep-ctrl-main" id="ep-btn-playpause" title="Play / Pause">⏸</button>
    <button class="ep-ctrl-btn" id="ep-btn-next"      title="Next">⏭</button>
  </div>

</div>
```

---

### 2. `static/style.css` — Append expanded player styles

Add these rules at the very end of `style.css`:

```css
/* ============================================================
   PHASE 5 — Expanded Player & Spectrum Visualizer
   ============================================================ */

/* ── Expand icon button on the compact playbar ── */
.expand-btn {
  margin-left: auto;          /* push to far right of playbar */
  flex-shrink: 0;
  background: none;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: var(--radius);
  padding: 6px 10px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
  line-height: 1;
}
.expand-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-color: var(--border-hover);
}

/* ── Expanded player overlay ──────────────────── */
.expanded-player {
  position: fixed;
  top: var(--topnav-h);      /* sits just below the navbar */
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--bg-primary);
  z-index: 98;               /* below navbar (100) but above everything else */
  display: flex;
  flex-direction: column;
  gap: 0;

  /* Slide-in/out animation */
  transform: translateY(100%);
  transition: transform 0.32s cubic-bezier(0.4, 0, 0.2, 1);
  will-change: transform;
}
.expanded-player.ep-open {
  transform: translateY(0);
}

/* ── Expanded player header ─────────────────────── */
.ep-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 20px 28px 12px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}
.ep-track-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.ep-now-label {
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 1.2px;
  text-transform: uppercase;
  color: var(--text-muted);
}
.ep-track-name {
  font-size: 1.3rem;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 70vw;
}
.ep-mode-badge {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 20px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  align-self: flex-start;
}
.ep-mode-badge.sonos   { background: var(--accent-dim); color: var(--accent); }
.ep-mode-badge.browser { background: rgba(100,140,255,0.15); color: #6699ff; }

.ep-close-btn {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-secondary);
  border-radius: var(--radius);
  padding: 8px 10px;
  cursor: pointer;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
  margin-left: 16px;
}
.ep-close-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

/* ── Spectrum visualizer area ─────────────────── */
.ep-viz-wrap {
  flex: 1;                   /* takes all remaining vertical space */
  position: relative;
  background: #000;
  overflow: hidden;
  min-height: 0;             /* flex shrink fix */
}

#ep-canvas {
  display: block;
  width: 100%;
  height: 100%;
  /* canvas drawing resolution is set by JS — CSS just stretches it */
}

/* Overlay messages inside the viz area */
.ep-viz-unavail,
.ep-viz-waiting {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: rgba(0, 0, 0, 0.75);
  color: var(--text-secondary);
  font-size: 0.9rem;
  text-align: center;
  padding: 20px;
}
.ep-viz-unavail.hidden,
.ep-viz-waiting.hidden  { display: none; }
.ep-viz-unavail-icon    { font-size: 2.5rem; }
.ep-viz-unavail-msg     { font-weight: 600; color: var(--text-primary); }
.ep-viz-unavail-sub     { font-size: 0.8rem; color: var(--text-muted); max-width: 340px; }

/* ── Granularity controls ─────────────────────── */
.ep-granularity {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 20px;
  flex-shrink: 0;
  border-top: 1px solid var(--border);
}
.ep-granularity-label {
  font-size: 0.78rem;
  color: var(--text-muted);
  margin-right: 4px;
  text-transform: uppercase;
  letter-spacing: 0.6px;
}
.ep-grain-btn {
  padding: 6px 18px;
  font-size: 0.82rem;
  font-weight: 500;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.ep-grain-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.ep-grain-btn.ep-grain-active {
  background: #223355;        /* matches sample: #335 */
  color: #fff;
  border-color: #6688aa;     /* matches sample: #68a */
}

/* ── Large playback controls ──────────────────── */
.ep-controls {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 20px;
  padding: 16px 20px 24px;
  flex-shrink: 0;
  border-top: 1px solid var(--border);
}
.ep-ctrl-btn {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  color: var(--text-primary);
  border-radius: 50%;
  width: 52px;
  height: 52px;
  font-size: 1.3rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, border-color 0.15s, transform 0.1s;
  flex-shrink: 0;
}
.ep-ctrl-btn:hover {
  background: var(--bg-hover);
  border-color: var(--border-hover);
}
.ep-ctrl-btn:active { transform: scale(0.93); }
.ep-ctrl-main {
  width: 68px;
  height: 68px;
  font-size: 1.6rem;
  background: var(--accent);
  border-color: var(--accent);
  color: #000;
}
.ep-ctrl-main:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
}
```

---

### 3. `static/app.js` — Append expanded player + visualizer logic

Append the entire block below to the end of `app.js`. Do not modify any existing code.

```javascript
/* ============================================================
   PHASE 5 — Expanded Player & Microphone Spectrum Visualizer
   ============================================================ */

// ── Visualizer state ─────────────────────────────────────────
// Kept module-level so the mic stream and AudioContext survive
// open/close cycles without re-requesting permission.
const viz = {
    audioCtx:    null,    // AudioContext (created once)
    analyser:    null,    // AnalyserNode (created once)
    stream:      null,    // MediaStream from getUserMedia (kept open)
    bufferLen:   0,
    dataArray:   null,    // Uint8Array for frequency data
    animFrameId: null,    // requestAnimationFrame handle
    binsPerBar:  4,       // DEFAULT = 4 (Medium) — matches sample code default
    ready:       false,   // true once mic is set up successfully
};

// ── Canvas ref (set once overlay opens) ──────────────────────
let epCanvas = null;
let epCtx    = null;

// ── DOM refs for expanded player ─────────────────────────────
const expandedPlayer  = document.getElementById('expanded-player');
const expandBtn       = document.getElementById('expand-player-btn');
const epCloseBtn      = document.getElementById('ep-close-btn');
const epTrackName     = document.getElementById('ep-track-name');
const epModeBadge     = document.getElementById('ep-mode-badge');
const epBtnPrev       = document.getElementById('ep-btn-prev');
const epBtnPlayPause  = document.getElementById('ep-btn-playpause');
const epBtnNext       = document.getElementById('ep-btn-next');
const epVizUnavail    = document.getElementById('ep-viz-unavail');
const epVizWaiting    = document.getElementById('ep-viz-waiting');

// ── Init on DOM ready ────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initExpandedPlayer);

function initExpandedPlayer() {
    epCanvas = document.getElementById('ep-canvas');
    epCtx    = epCanvas ? epCanvas.getContext('2d') : null;

    // Open/close
    expandBtn?.addEventListener('click',   openExpandedPlayer);
    epCloseBtn?.addEventListener('click',  closeExpandedPlayer);

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && expandedPlayer?.classList.contains('ep-open')) {
            closeExpandedPlayer();
        }
    });

    // Expanded player transport controls — delegates to Phase 4 handlers
    epBtnPrev?.addEventListener('click',      onPrev);
    epBtnNext?.addEventListener('click',      onNext);
    epBtnPlayPause?.addEventListener('click', onPlayPause);

    // Granularity buttons
    document.querySelectorAll('.ep-grain-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            viz.binsPerBar = Number(btn.dataset.bins);
            document.querySelectorAll('.ep-grain-btn').forEach(b =>
                b.classList.remove('ep-grain-active'));
            btn.classList.add('ep-grain-active');
        });
    });

    // Keep canvas drawing resolution in sync with its CSS size
    window.addEventListener('resize', syncCanvasSize);
}

// ── Open / close ─────────────────────────────────────────────

function openExpandedPlayer() {
    if (!expandedPlayer) return;

    // Sync track info from the compact playbar
    syncEpTrackInfo();

    expandedPlayer.classList.add('ep-open');
    expandedPlayer.setAttribute('aria-hidden', 'false');

    // Size canvas to its container
    syncCanvasSize();

    // Start or resume the visualizer
    startVisualizer();
}

function closeExpandedPlayer() {
    if (!expandedPlayer) return;
    expandedPlayer.classList.remove('ep-open');
    expandedPlayer.setAttribute('aria-hidden', 'true');

    // Cancel draw loop (mic stream stays open for instant re-open)
    stopDrawLoop();
}

// ── Sync track info label ─────────────────────────────────────
// Mirrors whatever the compact playbar currently shows.
// Also called by Phase 4's updateNowPlaying via an override below.

function syncEpTrackInfo() {
    if (epTrackName) {
        epTrackName.textContent = playback.currentTitle || '—';
    }
    if (epModeBadge && playback.mode) {
        epModeBadge.textContent = playback.mode === 'sonos' ? 'Sonos' : 'Browser';
        epModeBadge.className   = `ep-mode-badge ${playback.mode}`;
    }
}

// Override Phase 4's updateNowPlaying to also update the expanded player
// whenever it's open. We wrap the original function.
(function patchUpdateNowPlaying() {
    const _original = window.updateNowPlaying || updateNowPlaying;
    const patched = function(title, mode) {
        _original(title, mode);
        // If expanded player is open, keep it in sync
        if (expandedPlayer?.classList.contains('ep-open')) {
            syncEpTrackInfo();
        }
        // Mirror pause/play icon in expanded player
        syncEpPlayPauseIcon();
    };
    // Replace in global scope if it was declared with `function`
    window._patchedUpdateNowPlaying = patched;
})();

// Also patch setPlayPauseBtn so the expanded player's ⏸/▶ icon stays in sync
const _origSetPlayPauseBtn = typeof setPlayPauseBtn === 'function' ? setPlayPauseBtn : null;
function setPlayPauseBtn(isPlaying) {
    // Call original Phase 4 logic (updates compact bar)
    if (_origSetPlayPauseBtn) _origSetPlayPauseBtn(isPlaying);
    syncEpPlayPauseIcon();
}

function syncEpPlayPauseIcon() {
    if (epBtnPlayPause) {
        epBtnPlayPause.textContent = playback.isPlaying ? '⏸' : '▶';
    }
}

// ── Canvas sizing ─────────────────────────────────────────────
// The canvas element's drawing resolution (canvas.width / canvas.height)
// MUST match its rendered CSS pixel size, otherwise the bar math is wrong.
// `getVisibleBinCount` uses canvas.width directly (as in the sample code).

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

// ── Microphone + Web Audio setup ─────────────────────────────

async function startVisualizer() {
    // Show waiting state
    epVizWaiting?.classList.remove('hidden');
    epVizUnavail?.classList.add('hidden');

    if (!viz.ready) {
        // First open — request mic permission and build the audio graph
        try {
            viz.stream = await navigator.mediaDevices.getUserMedia({ audio: true });

            viz.audioCtx = new (window.AudioContext || window.webkitAudioContext)();

            const source  = viz.audioCtx.createMediaStreamSource(viz.stream);

            viz.analyser  = viz.audioCtx.createAnalyser();
            viz.analyser.fftSize               = 2048;   // exact value from sample
            viz.analyser.smoothingTimeConstant = 0.8;    // exact value from sample

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
        // AudioContext may be suspended after a long pause
        await viz.audioCtx.resume();
    }

    epVizWaiting?.classList.add('hidden');

    // Start the draw loop
    startDrawLoop();
}

// ── Draw loop ─────────────────────────────────────────────────

function startDrawLoop() {
    stopDrawLoop();  // cancel any existing frame first
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

// ── Spectrum bar drawing (from sample code — preserved exactly) ──────────
//
// IMPORTANT: these two functions are adapted directly from analyzer_ex.html.
// The math is identical. The only difference is they use `epCanvas` and `epCtx`
// (our expanded player's canvas) instead of the sample's `canvas` / `ctx`.
// `viz.binsPerBar` replaces the sample's module-level `binsPerBar`.
// `canvas.width` references in the sample map to `epCanvas.width` here.

function getVisibleBinCount(bufferLength) {
    // Original comment from sample:
    // Compute how many bins the original design showed
    // (barWidth = canvasW/bufferLen*2.5, gap 1px).
    // We reuse that same frequency range for all three modes.
    const singleBarWidth = epCanvas.width / bufferLength * 2.5;
    return Math.floor(epCanvas.width / (singleBarWidth + 1));
}

function drawSpectrumBars(dataArray, bufferLength) {
    const visibleBins = getVisibleBinCount(bufferLength);
    const barCount    = Math.ceil(visibleBins / viz.binsPerBar);
    const barWidth    = (epCanvas.width - barCount) / barCount; // leave 1px gap per bar

    // Clear to black (matches sample: ctx.fillStyle = "#000")
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

        // Original color formula from sample — preserved verbatim:
        epCtx.fillStyle = `rgb(${peak + 50}, ${255 - peak}, 100)`;
        epCtx.fillRect(x, epCanvas.height - barHeight, Math.max(1, barWidth), barHeight);
    }
}
```

---

## Integration Notes Between Phases

### `setPlayPauseBtn` patching
Phase 4 declares `setPlayPauseBtn` as a regular `function`. Phase 5 re-declares it, which in JS means the Phase 5 declaration wins (functions are hoisted but the last declaration takes effect). The Phase 5 version calls the Phase 4 original (stored before overriding) and then also updates the expanded player icon. **This only works if the Phase 5 JS block is appended after Phase 4's block in the same `app.js` file.**

If `setPlayPauseBtn` is instead an arrow function (`const setPlayPauseBtn = ...`), the patching approach must change to a wrapper:
```javascript
const _origSetPlayPauseBtn = setPlayPauseBtn;
// Cannot re-declare a const — instead, call syncEpPlayPauseIcon() directly
// inside onPlayPause(), onNext(), onPrev() via those existing functions.
```
Check Phase 4's declaration and adjust accordingly.

### Mic stream lifetime
The `MediaStream` (`viz.stream`) is held open permanently once granted. This prevents the browser from showing the "microphone in use" indicator from flickering on every open/close. The `AudioContext` and `AnalyserNode` are also reused. Only the `requestAnimationFrame` loop is started and stopped. This means:
- **First open:** prompts for mic permission (browser native dialog)
- **Subsequent opens:** instant, no permission prompt
- **Tab close:** browser automatically releases the mic stream

If you want to release the mic when the overlay closes (e.g. to turn off the mic indicator), add to `closeExpandedPlayer()`:
```javascript
viz.stream?.getTracks().forEach(t => t.stop());
viz.ready = false;  // force re-init on next open
```

---

## API Endpoints Changed
None. This phase is entirely frontend.

---

## Validation Steps

### 1. Expand button visible
- Start playback (click "▶ Browser" on any file) — the compact playbar appears.
- A small ⛶ icon button should be visible at the far right of the playbar.

### 2. Open expanded player
- Click the ⛶ expand button.
- The expanded player slides up from the bottom, covering everything below the navbar.
- Track name shown at top matches what's in the compact playbar.
- Mode badge (Sonos / Browser) shown correctly.

### 3. Mic permission prompt
- A native browser permission dialog should appear asking for microphone access.
- The "Waiting for microphone…" spinner is visible in the canvas area during the prompt.
- **Grant permission** → spinner disappears, spectrum visualizer starts animating.
- **Deny permission** → spinner disappears, "Microphone unavailable" message appears with sub-text.

### 4. Spectrum visualizer (granted)
- Canvas fills the dark area with animated bars.
- Make noise (clap, speak) — bars should spike reactively.
- If playing music via browser audio or Sonos (nearby speaker), bars respond to the room audio.
- Default state is **Medium** granularity (`binsPerBar = 4`) — visually a moderate bar count.

### 5. Granularity toggle
- Click **Fine** — many thin bars appear, covering the full frequency range in fine detail.
- Click **Coarse** — fewer, wider bars.
- Click **Medium** — returns to default. The "Medium" button should start with `.ep-grain-active` class.
- Verify the color gradient changes (`rgb(peak+50, 255-peak, 100)`) — low-energy bars appear greenish/dim, high-energy bars shift toward orange/bright.

### 6. Playback controls in expanded view
- ⏮ ⏸ ⏭ buttons work identically to the compact bar.
- Pause via expanded player → compact bar's icon also updates to ▶.
- Skip via expanded player → track name updates in both places.

### 7. Close button
- Click ✕ or press Escape → overlay slides back down.
- Compact playbar is still visible and controls still work.
- Re-open expanded player → visualizer resumes instantly (no new permission prompt).

### 8. Canvas resize
- Open expanded player, then resize the browser window.
- Canvas bars should rescale correctly — no squished or clipped bars.
- (Canvas `width`/`height` attributes are re-synced on `window.resize`.)

### 9. Nothing playing edge case
- Before starting any playback, the expand button is NOT visible (playbar is hidden).
- Once something starts playing, the expand button appears with the playbar.
- Expand button should not appear if the playbar is hidden.

---

## Notes & Gotchas

### Canvas attribute vs CSS size
The `<canvas>` element has two separate sizing concepts:
- **CSS size** (`width: 100%; height: 100%` in `.css`) — controls layout/display
- **Drawing resolution** (`canvas.width`, `canvas.height` attributes) — controls the pixel grid used by `getContext('2d')`

The `getVisibleBinCount` and `drawSpectrumBars` functions use `epCanvas.width` (the attribute) directly, exactly as in the sample. If the attribute is not kept in sync with the rendered size, bars will be drawn in the wrong proportions. `syncCanvasSize()` handles this, called on open and on `window.resize`.

### AudioContext autoplay policy
Chrome and Safari require an AudioContext to be created (or resumed) inside a user gesture handler. `openExpandedPlayer()` is already called from a button click, so this is satisfied. However, if the AudioContext was created and then suspended (e.g. the tab was backgrounded), `viz.audioCtx.resume()` is called on re-open. This handles the most common suspended-context case.

### `fftSize = 2048` gives `frequencyBinCount = 1024`
`frequencyBinCount` is always `fftSize / 2`. With `fftSize = 2048`, `bufferLength = 1024`. The `getVisibleBinCount` formula limits how many of those 1024 bins are actually drawn, which is why the visualizer doesn't show the entire ultrasonic spectrum — just the audible portion in a reasonable bar count. This matches the sample exactly.

### Granularity button default state
The HTML sets `ep-grain-active` on the **Medium** button (`data-bins="4"`) by default. The JS reads `.ep-grain-btn[data-bins="4"]` as the initial active state. `viz.binsPerBar` is also initialized to `4`. Both must agree. Do not change either without changing the other.

### The expand button only makes sense when playing
The expand button is inside `#playbar` which is hidden by default and only shown when `updateNowPlaying()` is called (in Phase 4, via `showPlaybar()`). So the expand button naturally only appears when something is playing — no extra visibility logic needed.

### soco vs Sonos track-title updates
When Sonos advances tracks in a queue, `syncSonosState()` (Phase 4) polls every 3 seconds and calls `updateNowPlaying(newTitle, 'sonos')`. The `patchUpdateNowPlaying` wrapper in Phase 5 intercepts this and also updates `ep-track-name`, so the expanded player always shows the current track — even during queue playback with Sonos doing the advancing.
