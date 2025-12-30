// ======================================================
// PiCam Controller — Frontend JS (copy-paste full file)
// ======================================================

// ----------------------- Globals -----------------------
const POLL_EVERY_MS = 2000;
let WINDOW_SEC = 30;                 // metrics window
const WINDOW_MS = () => WINDOW_SEC * 1000;
const MAX_POINTS = 5000;               // charts safety cap

// ----------------------- Utils -------------------------
async function api(path, opts = {}) {
  const r = await fetch(path, { cache: "no-store", ...opts });
  const txt = await r.text();
  try { return JSON.parse(txt) } catch { return { text: txt, status: r.status } }
}
function setDonut(el, pctFree) {
  const clamped = Math.max(0, Math.min(100, pctFree || 0));
  el.setAttribute("stroke-dasharray", `${clamped} ${100 - clamped}`);
}

// ======================================================
// Theme (Dark/Light) with localStorage
// ======================================================
const ThemeController = (() => {
  const KEY = 'theme'; // 'light' or 'dark'

  function apply(mode) {
    document.body.classList.toggle('light', mode === 'light');
    const icon = document.getElementById('theme-icon');
    if (icon) icon.textContent = (mode === 'light') ? '🌞' : '🌙';
    // force charts to refresh with the new grid color
    if (typeof redrawAllSparklines === 'function') redrawAllSparklines();
  }

  function load() {
    const stored = localStorage.getItem(KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return 'dark';
  }

  function save(mode) { localStorage.setItem(KEY, mode); }

  function toggle() {
    const current = document.body.classList.contains('light') ? 'light' : 'dark';
    const next = current === 'light' ? 'dark' : 'light';
    apply(next); save(next);
  }

  function init() {
    apply(load());
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.addEventListener('click', toggle);
  }

  return { init, toggle };
})();

// ======================================================
// Refresh button
// ======================================================
const RefreshController = (() => {
  function flash(msg, ok = true) {
    // lightweight toast near the button
    let el = document.getElementById('refresh-toast');
    if (!el) {
      el = document.createElement('div');
      el.id = 'refresh-toast';
      el.style.position = 'fixed';
      el.style.top = '46px';
      el.style.left = '14px';
      el.style.zIndex = '3001';
      el.style.padding = '6px 10px';
      el.style.borderRadius = '8px';
      el.style.border = '1px solid var(--border)';
      el.style.background = 'var(--card-bg)';
      el.style.color = 'var(--text)';
      el.style.fontSize = '12px';
      el.style.boxShadow = '0 0 6px rgba(0,0,0,.25)';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.style.opacity = '1';
    el.style.borderColor = ok ? '#1e784d' : '#a12a2a';
    el.style.transition = 'opacity .3s ease';
    setTimeout(() => el.style.opacity = '0', 1200);
  }

  async function callRefresh() {
    const btn = document.getElementById('refresh-btn');
    if (!btn) return;

    // spin the icon right away
    const icon = btn.querySelector('svg');
    const anim = icon?.animate(
      [{ transform: 'rotate(0deg)' }, { transform: 'rotate(360deg)' }],
      { duration: 500 }
    );

    btn.disabled = true;
    try {
      const res = await fetch('/refresh', { method: 'POST', cache: 'no-store' });
      if (!res.ok) {
        // Endpoint missing or error
        console.warn('Refresh endpoint error:', res.status, res.statusText);
        flash('Refresh endpoint not ready', /*ok=*/false);

        // Optional: force a hard reload as a fallback
        // location.reload();
        return;
      }
      // We don’t care about the payload, but you can:
      // const data = await res.json().catch(() => ({}));
      flash('Refreshed ✓', /*ok=*/true);
    } catch (e) {
      console.warn('Refresh call failed:', e);
      flash('Network error', /*ok=*/false);
      // Optional reload fallback:
      // location.reload();
    } finally {
      await anim?.finished?.catch(() => { });
      btn.disabled = false;
    }
  }

  function init() {
    const btn = document.getElementById('refresh-btn');
    if (btn) btn.addEventListener('click', callRefresh);
  }
  return { init };
})();

// ======================================================
// PanelController (mutual exclusivity for any registered panel)
// ======================================================
const PanelController = (() => {
  // map: { panelName: () => closeFn }
  const closers = {};

  function register(map) {
    // Accept either {name: closeFn} or {name: {close: closeFn}}
    for (const [name, val] of Object.entries(map || {})) {
      if (typeof val === 'function') {
        closers[name] = val;
      } else if (val && typeof val.close === 'function') {
        closers[name] = val.close;
      }
    }
  }

  // Close all except the one named in `except` (or close all if null)
  function closeAll(except = null) {
    for (const [name, fn] of Object.entries(closers)) {
      if (name !== except && typeof fn === 'function') {
        try { fn(); } catch { /* no-op */ }
      }
    }
  }

  return { register, closeAll };
})();


// ======================================================
// Status / Metrics / Charts
// ======================================================
function setStatus(running, sinceTs) {
  const el = document.getElementById('status');
  const cls = running ? 'ok' : 'warn';
  el.className = 'status ' + cls;
  if (running) {
    const since = sinceTs ? new Date(sinceTs * 1000).toLocaleTimeString() : '—';
    el.innerHTML = '🟢 Recording <span class="mono">(since ' + since + ')</span>';
  } else {
    el.innerHTML = '🔴 Not recording';
  }
}

async function refreshStatus() {
  const s = await api('/status');
  setStatus(s.running, s.started_ts);
  document.getElementById('save_dir').textContent = s.save_dir ?? '—';
  document.getElementById('disk_path').textContent = s.save_dir ?? '—';
}

async function startCapture() {
  const res = await api('/start');
  document.getElementById('log').textContent = JSON.stringify(res, null, 2);
  refreshStatus();
}

async function stopCapture() {
  const res = await api('/stop');
  document.getElementById('log').textContent = JSON.stringify(res, null, 2);
  setTimeout(refreshStatus, 300);
}

// -------- Still capture (compact UI feedback) --------
async function captureStill() {
  const logEl = document.getElementById('log');
  const timeEl = document.getElementById('last_image_time');
  const badgeEl = document.getElementById('img_captured_badge');

  try {
    const res = await fetch('/capture_image', { method: 'POST' });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      timeEl.textContent = '—';
      badgeEl.textContent = 'Failed';
      badgeEl.classList.remove('hide'); badgeEl.classList.add('warn');
      setTimeout(() => { badgeEl.classList.add('hide'); badgeEl.classList.remove('warn'); }, 2000);
      logEl.textContent = 'Capture failed';
      return;
    }

    timeEl.textContent = new Date().toLocaleTimeString();
    badgeEl.textContent = 'Saved';
    badgeEl.classList.remove('hide');
    setTimeout(() => badgeEl.classList.add('hide'), 1800);
    logEl.textContent = 'Image captured successfully.';
  } catch (e) {
    timeEl.textContent = '—';
    badgeEl.textContent = 'Error';
    badgeEl.classList.remove('hide'); badgeEl.classList.add('warn');
    setTimeout(() => { badgeEl.classList.add('hide'); badgeEl.classList.remove('warn'); }, 2000);
    logEl.textContent = 'Error: ' + e;
  }
}

// -------- Charts buffers --------
const buf = { cur: [], vol: [], pow: [], cpu: [], ram: [], mhz: [] };

function prune(a) {
  const cutoff = performance.now() - WINDOW_MS();
  while (a.length && a[0][0] < cutoff) a.shift();
  while (a.length > MAX_POINTS) a.shift();
}
function push(bufname, v, tMs) {
  if (v == null) return;
  const a = buf[bufname];
  a.push([tMs, v]);
  prune(a);
}

function drawSparkline(canvas, series, { min = null, max = null } = {}) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.clientWidth * devicePixelRatio;
  const h = canvas.height = canvas.clientHeight * devicePixelRatio;
  ctx.clearRect(0, 0, w, h);
  if (!series.length) return;

  const now = performance.now();
  const dtWindow = WINDOW_MS();
  const t0 = Math.min(series[0][0], now - dtWindow);
  const t1 = Math.max(series[series.length - 1][0], now);
  const dt = Math.max(1, t1 - t0);

  const values = series.map(p => p[1]).filter(v => v != null && isFinite(v));
  if (!values.length) return;
  let lo = (min ?? Math.min(...values));
  let hi = (max ?? Math.max(...values));
  if (!isFinite(lo) || !isFinite(hi) || hi === lo) { lo = lo || 0; hi = lo + 1; }

  const pad = 6 * devicePixelRatio;

  // --- single mid grid line: white in dark mode, gray in light mode ---
  const isLight = document.body.classList.contains('light');
  const gridColor = isLight ? '#2a3346' : '#ffffff';
  ctx.globalAlpha = 0.25;
  ctx.strokeStyle = gridColor;
  ctx.beginPath();
  const midY = h - pad - (((lo + hi) / 2 - lo) / (hi - lo)) * (h - 2 * pad);
  ctx.moveTo(pad, midY);
  ctx.lineTo(w - pad, midY);
  ctx.stroke();
  ctx.globalAlpha = 1;

  // line
  ctx.lineWidth = 2 * devicePixelRatio;
  ctx.strokeStyle = "#7dd3fc";
  ctx.beginPath();
  for (let i = 0; i < series.length; i++) {
    const [t, v] = series[i];
    const x = pad + ((t - t0) / dt) * (w - 2 * pad);
    const y = h - pad - ((v - lo) / (hi - lo)) * (h - 2 * pad);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function redrawAllSparklines() {
  drawSparkline(document.getElementById('cur'), buf.cur, { min: 0 });
  drawSparkline(document.getElementById('vol'), buf.vol);
  drawSparkline(document.getElementById('pow'), buf.vol);
  drawSparkline(document.getElementById('cpu'), buf.cpu, { min: 0, max: 100 });
  drawSparkline(document.getElementById('ram'), buf.ram, { min: 0, max: 100 });
  drawSparkline(document.getElementById('mhz'), buf.mhz);
}


async function tick() {
  const m = await api('/metrics');
  const now = performance.now();

  document.getElementById('cpu_temp').innerHTML = (m.cpu.temp_c ?? '—') + '<span class="unit">°C</span>';
  document.getElementById('gpu_temp').innerHTML = (m.gpu.temp_c ?? '—') + '<span class="unit">°C</span>';
  document.getElementById('disk_free').innerHTML = (m.disk.free_pct ?? '—') + '<span class="unit">%</span>';
  setDonut(document.getElementById('donut'), m.disk.free_pct ?? 0);

  push('cur', m.sensors.current_a, now);
  push('vol', m.sensors.voltage_v, now);
  push('pow', m.sensors.power_w, now);
  push('cpu', m.cpu.util_pct, now);
  push('ram', m.ram.used_pct, now);
  push('mhz', m.cpu.freq_mhz, now);

  document.getElementById('cur_now').textContent = m.sensors.current_a ?? '—';
  document.getElementById('vol_now').textContent = m.sensors.voltage_v ?? '—';
  document.getElementById('pow_now').textContent = m.sensors.power_w ?? '—';
  document.getElementById('cpu_now').textContent = m.cpu.util_pct ?? '—';
  document.getElementById('ram_now').textContent = m.ram.used_pct ?? '—';
  document.getElementById('mhz_now').textContent = m.cpu.freq_mhz ?? '—';

  drawSparkline(document.getElementById('cur'), buf.cur, { min: 0 });
  drawSparkline(document.getElementById('vol'), buf.vol);
  drawSparkline(document.getElementById('pow'), buf.pow);
  drawSparkline(document.getElementById('cpu'), buf.cpu, { min: 0, max: 100 });
  drawSparkline(document.getElementById('ram'), buf.ram, { min: 0, max: 100 });
  drawSparkline(document.getElementById('mhz'), buf.mhz);
}

// -------- Window chip controls --------
function setupWindowChips() {
  const allChips = Array.from(document.querySelectorAll('.chip'));
  function activate(sec) {
    WINDOW_SEC = Number(sec);
    allChips.forEach(c => {
      c.classList.toggle('active', Number(c.dataset.win) === WINDOW_SEC);
    });
    Object.values(buf).forEach(prune);
    drawSparkline(document.getElementById('cur'), buf.cur, { min: 0 });
    drawSparkline(document.getElementById('vol'), buf.vol);
    drawSparkline(document.getElementById('pow'), buf.pow);
    drawSparkline(document.getElementById('cpu'), buf.cpu, { min: 0, max: 100 });
    drawSparkline(document.getElementById('ram'), buf.ram, { min: 0, max: 100 });
    drawSparkline(document.getElementById('mhz'), buf.mhz);
  }
  allChips.forEach(chip => chip.addEventListener('click', () => activate(chip.dataset.win)));
  activate(document.querySelector('.chip.active')?.dataset.win ?? 30);
}

// ======================================================
// SHELL Drawer (exclusive + 'cls' to clear)
// ======================================================
(function () {
  const drawer = document.getElementById('shell-drawer');
  const toggle = document.getElementById('shell-toggle');
  const runBtn = document.getElementById('shell-run');
  const clearBtn = document.getElementById('shell-clear');
  const input = document.getElementById('shell-input');
  const tout = document.getElementById('shell-timeout');
  const output = document.getElementById('shell-output');
  const status = document.getElementById('shell-status');

  function isOpen() { return drawer.classList.contains('open'); }
  function openDrawer() {
    PanelController.closeAll('shell');
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    toggle.classList.add('active');
    setTimeout(() => input.focus(), 120);
  }
  function closeDrawer() {
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    toggle.classList.remove('active');
  }
  function toggleDrawer() { isOpen() ? closeDrawer() : openDrawer(); }

  PanelController.register({ shell: { close: closeDrawer } });

  function appendOut(kind, text) {
    const prefix = kind === 'stderr' ? '[stderr] ' : '';
    output.textContent += (prefix + (text || '')).replace(/\r\n/g, '\n') + '\n';
    output.scrollTop = output.scrollHeight;
  }

  async function runCommand() {
    const cmd = (input.value || '').trim();
    const timeout = Math.max(1, Math.min(parseInt(tout.value || '15', 10), 300));
    if (!cmd) return;

    // intercept 'cls'
    if (cmd.toLowerCase() === 'cls') {
      output.textContent = '';
      input.select();
      return;
    }

    runBtn.disabled = true;
    status.textContent = 'Running…';
    output.textContent += `$ ${cmd}\n`;
    try {
      const res = await fetch('/shell', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cmd, timeout })
      });
      if (!res.ok) {
        appendOut('stderr', `HTTP ${res.status}: ${res.statusText}`);
      } else {
        const data = await res.json();
        if (data.stdout) appendOut('stdout', data.stdout);
        if (data.stderr) appendOut('stderr', data.stderr);
        if (!data.stdout && !data.stderr) appendOut('stdout', '[no output]');
        output.textContent += `[exit=${data.code ?? '—'} ok=${data.ok} elapsed=${data.elapsed_sec ?? '—'}s${data.timeout ? ' TIMEOUT' : ''}]\n\n`;
      }
    } catch (e) {
      appendOut('stderr', String(e));
    } finally {
      status.textContent = '';
      runBtn.disabled = false;
      input.select();
    }
  }

  toggle.addEventListener('click', toggleDrawer);
  clearBtn.addEventListener('click', () => { output.textContent = ''; });
  runBtn.addEventListener('click', runCommand);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) runCommand();
    if (e.key === 'Escape') closeDrawer();
  });
})();

// ======================================================
// CONFIG Drawer (exclusive + live apply + new fields)
// ======================================================
(function () {
  const drawer = document.getElementById('config-drawer');
  const toggle = document.getElementById('config-toggle');

  const saveDirInput = document.getElementById('cfg-save-dir');
  const saveDirReset = document.getElementById('cfg-save-dir-reset');
  const ledToggle = document.getElementById('cfg-led');
  const modeNote = document.getElementById('cfg-mode-note');
  const ledNote = document.getElementById('cfg-led-note');
  const imgResInput = document.getElementById('cfg-img-res');
  const imgResReset = document.getElementById('cfg-img-res-reset');
  const vidResInput = document.getElementById('cfg-vid-res');
  const vidFpsInput = document.getElementById('cfg-vid-fps');
  const vidReset = document.getElementById('cfg-vid-reset');
  const logHoursInput = document.getElementById('cfg-log-hours');
  const logHoursReset = document.getElementById('cfg-log-hours-default');

  function isOpen() { return drawer.classList.contains('open'); }
  function openDrawer() {
    PanelController.closeAll('config');
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    toggle.classList.add('active');
  }
  function closeDrawer() {
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    toggle.classList.remove('active');
  }
  function toggleDrawer() { isOpen() ? closeDrawer() : openDrawer(); }

  PanelController.register({ config: { close: closeDrawer } });

  async function loadConfig() {
    const cfg = await (await fetch('/config', { cache: 'no-store' })).json();

    saveDirInput.value = cfg.save_dir_current || '';
    modeNote.textContent = cfg.development_mode ? 'DEV mode' : 'PROD';
    ledToggle.checked = !!cfg.led_on;
    ledNote.textContent = cfg.development_mode ? ' (no-op in DEV)' : '';

    // NEW: populate res/fps with defaults & dataset defaults for reset buttons
    imgResInput.value = cfg.image_res_current || cfg.image_res_default || '640x480';
    imgResInput.dataset.default = cfg.image_res_default || '640x480';

    vidResInput.value = cfg.video_res_current || cfg.video_res_default || '640x480';
    vidResInput.dataset.default = cfg.video_res_default || '640x480';

    vidFpsInput.value = (cfg.video_fps_current ?? cfg.video_fps_default ?? 25);
    vidFpsInput.dataset.default = (cfg.video_fps_default ?? 25);

    // Also reflect save dir elsewhere in UI
    document.getElementById('save_dir').textContent = cfg.save_dir_current ?? '—';
    document.getElementById('disk_path').textContent = cfg.save_dir_current ?? '—';

    try {
      const lr = await (await fetch('/log/config', { cache: 'no-store' })).json();
      if (lr && lr.ok) {
        logHoursInput.value = lr.reset_hours ?? 24;
        logHoursInput.dataset.default = 24;
      } else {
        logHoursInput.value = 24;
        logHoursInput.dataset.default = 24;
      }
    } catch {
      logHoursInput.value = 24;
      logHoursInput.dataset.default = 24;
    }
  }

  // Debounced auto-apply for any input in this drawer
  let applyTimer = null;
  function scheduleApplyConfig() {
    if (applyTimer) clearTimeout(applyTimer);
    applyTimer = setTimeout(async () => {
      const payload = {
        save_dir: (saveDirInput.value || '').trim(),
        image_res: (imgResInput.value || '').trim(),
        video_res: (vidResInput.value || '').trim(),
        video_fps: parseInt(vidFpsInput.value || '25', 10)
      };
      await fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      refreshStatus();
    }, 300);
  }

  let logTimer = null;
  function scheduleApplyLogCfg() {
    if (logTimer) clearTimeout(logTimer);
    logTimer = setTimeout(async () => {
      const hrs = Math.max(1, Math.min(parseInt(logHoursInput.value || '24', 10), 720));
      await fetch('/log/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reset_hours: hrs })
      });
    }, 300);
  }


  async function restoreDefaultPath() {
    const r = await fetch('/config', { cache: 'no-store' });
    const cfg = await r.json();
    saveDirInput.value = cfg.save_dir_default || './outputs';
    scheduleApplyConfig();
  }

  function restoreImgDefault() {
    imgResInput.value = imgResInput.dataset.default || '640x480';
    scheduleApplyConfig();
  }
  function restoreVidDefault() {
    vidResInput.value = vidResInput.dataset.default || '640x480';
    vidFpsInput.value = vidFpsInput.dataset.default || 25;
    scheduleApplyConfig();
  }

  async function applyLed() {
    await fetch('/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ led_on: !!ledToggle.checked })
    });
  }

  toggle.addEventListener('click', async () => {
    toggleDrawer();
    if (isOpen()) await loadConfig();
  });

  // Auto-apply on change/typing
  saveDirInput.addEventListener('input', scheduleApplyConfig);
  imgResInput.addEventListener('input', scheduleApplyConfig);
  vidResInput.addEventListener('input', scheduleApplyConfig);
  vidFpsInput.addEventListener('input', scheduleApplyConfig);

  // Reset buttons
  saveDirReset.addEventListener('click', restoreDefaultPath);
  imgResReset.addEventListener('click', () => {
    imgResInput.value = imgResInput.dataset.default || '640x480';
    scheduleApplyConfig();
  });
  vidReset.addEventListener('click', () => {
    vidResInput.value = vidResInput.dataset.default || '640x480';
    vidFpsInput.value = vidFpsInput.dataset.default || 25;
    scheduleApplyConfig();
  });

  ledToggle.addEventListener('change', applyLed);

  logHoursInput.addEventListener('input', scheduleApplyLogCfg);
  logHoursReset.addEventListener('click', () => {
    logHoursInput.value = logHoursInput.dataset.default || 24;
    scheduleApplyLogCfg();
  });
})();

// ======================================================
// POWER (popover + modal confirm) — exclusive & robust
// ======================================================
(function () {
  const btn = document.getElementById('power-toggle');
  const pop = document.getElementById('power-pop');

  // Modal bits
  const modal = document.getElementById('confirm-modal');
  const titleEl = document.getElementById('confirm-title');
  // BUGFIX: match your HTML id="confirm-message"
  const msgEl = document.getElementById('confirm-message');
  const cancelBtn = document.getElementById('confirm-cancel');
  const okBtn = document.getElementById('confirm-ok');

  // Optional direct references if you gave the buttons IDs:
  const rebootBtn = document.querySelector('#power-pop [data-action="reboot"]');
  const shutdownBtn = document.querySelector('#power-pop [data-action="shutdown"]');

  let pendingAction = null;

  function isOpen() { return pop && pop.classList.contains('open'); }
  function openPop() {
    if (!pop) return console.error('[power] #power-pop not found');
    PanelController.closeAll('power');
    pop.classList.add('open');
    btn && btn.classList.add('active');
  }
  function closePop() {
    if (!pop) return;
    pop.classList.remove('open');
    btn && btn.classList.remove('active');
  }
  function togglePop() { isOpen() ? closePop() : openPop(); }

  PanelController.register({ power: { close: closePop } });

  // ---- Modal handling ----
  function showModal(action) {
    if (!modal) return console.error('[power] #confirm-modal not found');
    pendingAction = action;
    const label = action === 'reboot' ? 'Restart' : 'Shut Down';
    titleEl && (titleEl.textContent = `${label} Pi`);
    msgEl && (msgEl.textContent = `Are you sure you want to ${label.toLowerCase()} the Raspberry Pi?`);
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    pendingAction = null;
  }

  // Confirm action
  okBtn && okBtn.addEventListener('click', async () => {
    if (!pendingAction) return;
    const action = pendingAction;
    closeModal();
    closePop();
    try {
      const r = await fetch('/power', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        alert('Failed: ' + (data.error || data.message || r.statusText));
      }

    } catch (err) {
      alert('Error: ' + err);
    }
  });

  cancelBtn && cancelBtn.addEventListener('click', closeModal);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

  // Toggle popover from the rail button
  if (btn) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePop();
    });
  } else {
    console.warn('[power] #power-toggle not found');
  }

  // Close popover when clicking outside it
  document.addEventListener('click', (e) => {
    if (!pop) return;
    if (!pop.contains(e.target) && e.target !== btn) closePop();
  });

  // === Attach click handlers to the popover buttons ===
  // 1) Robust event delegation (works even if you re-render buttons)
  if (pop) {
    pop.addEventListener('click', (e) => {
      const actionBtn = e.target.closest('button[data-action]');
      if (!actionBtn) return;
      const action = actionBtn.getAttribute('data-action');
      if (action !== 'reboot' && action !== 'shutdown') {
        console.warn('[power] unknown action:', action);
        return;
      }
      showModal(action);
    });
  } else {
    console.error('[power] #power-pop not found; popover clicks won’t work');
  }

  // 2) Optional direct bindings too (in case delegation was removed/changed)
  rebootBtn && rebootBtn.addEventListener('click', () => showModal('reboot'));
  shutdownBtn && shutdownBtn.addEventListener('click', () => showModal('shutdown'));
})();

// ======================================================
// PREVIEW (popover + MJPEG in PROD, canvas placeholder in DEV)
// + Live controls (AE, Exposure, Gains, Bright/Contrast/Saturation/Sharpness)
// + Reset Defaults
// + 📸 Capture Image button placed UNDER the preview image and ABOVE the sliders
// ======================================================
(function () {
  const btn = document.getElementById('preview-toggle');
  const pop = document.getElementById('preview-pop');
  const feed = document.getElementById('preview-feed');
  const cvs = document.getElementById('preview-canvas');
  const note = document.getElementById('preview-note');

  let devAnim = null;
  let isDevMode = null; // resolved on first open
  let uiBuilt = false;

  // UI refs
  const ui = {};

  // ---------- Utilities ----------
  function isOpen() { return pop && pop.classList.contains('open'); }
  function openPop() {
    PanelController.closeAll('preview');
    pop.classList.add('open');
    btn && btn.classList.add('active');
  }
  function closePop() {
    pop.classList.remove('open');
    btn && btn.classList.remove('active');
    if (feed) feed.src = '';
    if (devAnim) { cancelAnimationFrame(devAnim); devAnim = null; }
  }
  function togglePop() { isOpen() ? closePop() : openPop(); }

  PanelController.register({ preview: { close: closePop } });

  // simple animated DEV placeholder
  function startDevAnim() {
    if (!cvs) return;
    const ctx = cvs.getContext('2d');
    const W = cvs.width, H = cvs.height;
    let t = 0;
    (function loop() {
      ctx.fillStyle = '#0b0f16';
      ctx.fillRect(0, 0, W, H);
      const cx = W / 2 + Math.cos(t / 20) * W / 4;
      const cy = H / 2 + Math.sin(t / 30) * H / 4;
      const r = 40 + 10 * Math.sin(t / 15);
      ctx.beginPath(); ctx.arc(cx, cy, r + 8, 0, Math.PI * 2);
      ctx.strokeStyle = '#2f81f7'; ctx.lineWidth = 6; ctx.stroke();
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fillStyle = '#1e784d'; ctx.fill();
      ctx.fillStyle = '#9da7b3'; ctx.font = '14px system-ui';
      ctx.fillText('DEV PREVIEW (no camera)', 12, H - 12);
      t++; devAnim = requestAnimationFrame(loop);
    })();
  }

  async function resolveMode() {
    if (isDevMode !== null) return isDevMode;
    try {
      const cfg = await (await fetch('/config', { cache: 'no-store' })).json();
      isDevMode = !!cfg.development_mode;
    } catch {
      isDevMode = true; // safest fallback
    }
    return isDevMode;
  }

  // ---------- Controls UI ----------
  function ensureControlsUI() {
    if (uiBuilt || !pop) return;
    uiBuilt = true;

    // --- Top toolbar with Capture button (sits below image, above sliders) ---
    const toolbar = document.createElement('div');
    toolbar.style.display = 'flex';
    toolbar.style.gap = '8px';
    toolbar.style.alignItems = 'center';
    toolbar.style.marginTop = '6px';
    toolbar.style.marginBottom = '6px';

    const capBtn = document.createElement('button');
    capBtn.textContent = '📸 Capture Image';
    capBtn.className = 'cfg-btn';
    capBtn.style.padding = '8px 12px';
    capBtn.id = 'pv-capture';

    const capMsg = document.createElement('span');
    capMsg.className = 'small muted mono';
    capMsg.style.marginLeft = '8px';

    toolbar.appendChild(capBtn);
    toolbar.appendChild(capMsg);

    // Place toolbar directly under the preview note (i.e., under the image)
    if (note) note.insertAdjacentElement('afterend', toolbar);

    // --- Controls grid panel (sliders) ---
    const panel = document.createElement('div');
    panel.id = 'preview-ctrls';
    panel.style.display = 'grid';
    panel.style.gridTemplateColumns = 'repeat(2, minmax(0,1fr))';
    panel.style.gap = '8px';
    panel.style.marginTop = '6px';

    function mkRow(label, input, rightEl = null) {
      const wrap = document.createElement('div');
      wrap.className = 'tile';
      wrap.style.display = 'flex';
      wrap.style.flexDirection = 'column';
      wrap.style.gap = '6px';
      wrap.style.padding = '8px';
      const head = document.createElement('div');
      head.className = 'small muted';
      head.style.display = 'flex';
      head.style.justifyContent = 'space-between';
      const l = document.createElement('span'); l.textContent = label;
      head.appendChild(l);
      if (rightEl) head.appendChild(rightEl);
      wrap.appendChild(head);
      wrap.appendChild(input);
      return wrap;
    }

    function mkRange(id, min, max, step, initVal, suffix = '') {
      const box = document.createElement('div');
      box.style.display = 'flex';
      box.style.alignItems = 'center';
      box.style.gap = '8px';

      const inp = document.createElement('input');
      inp.id = id;
      inp.type = 'range';
      inp.min = String(min);
      inp.max = String(max);
      inp.step = String(step);
      if (initVal !== undefined) inp.value = String(initVal);
      inp.className = 'cfg-inp';
      inp.style.padding = '0';
      inp.style.flex = '1';

      const val = document.createElement('span');
      val.className = 'small mono muted';
      val.textContent = (initVal ?? inp.value) + (suffix || '');

      inp.addEventListener('input', () => { val.textContent = inp.value + (suffix || ''); });

      box.appendChild(inp);
      box.appendChild(val);
      return { box, inp, val };
    }

    function mkCheck(id, text = 'Enabled') {
      const line = document.createElement('label');
      line.className = 'small';
      line.style.display = 'flex';
      line.style.alignItems = 'center';
      line.style.gap = '8px';
      const inp = document.createElement('input');
      inp.id = id;
      inp.type = 'checkbox';
      const txt = document.createElement('span'); txt.textContent = text;
      line.appendChild(inp); line.appendChild(txt);
      return { line, inp };
    }

    // ---- Controls ----
    const ae = mkCheck('pv-ae', 'Enabled'); ui.ae = ae.inp;

    // ExposureTime slider: 100–200000 μs (0.1–200 ms), step 100
    const et = mkRange('pv-exposure', 100, 200000, 100, 10000, ' μs'); ui.et = et.inp;

    // Analogue/Digital Gain sliders: 1.0–16.0, step 0.1
    const ag = mkRange('pv-analoggain', 1.0, 16.0, 0.1, 1.0, '×'); ui.ag = ag.inp;
    const dg = mkRange('pv-digitalgain', 1.0, 16.0, 0.1, 1.0, '×'); ui.dg = dg.inp;

    // Tone sliders
    const bri = mkRange('pv-brightness', -1.0, 1.0, 0.05, 0.0); ui.bri = bri.inp;
    const con = mkRange('pv-contrast', 0.0, 2.0, 0.05, 1.0); ui.con = con.inp;
    const sat = mkRange('pv-saturation', 0.0, 2.0, 0.05, 1.0); ui.sat = sat.inp;
    const sha = mkRange('pv-sharpness', 0.0, 2.0, 0.05, 1.0); ui.sha = sha.inp;

    // Reset button (top-right of the AE tile)
    const resetBtn = document.createElement('button');
    resetBtn.textContent = 'Reset to Defaults';
    resetBtn.className = 'cfg-btn';
    resetBtn.style.padding = '6px 10px';

    // Layout: PANELS GO UNDER THE TOOLBAR (so capture button is above them)
    panel.appendChild(mkRow('Auto Exposure (AeEnable)', ae.line, resetBtn));
    panel.appendChild(mkRow('Exposure Time (μs)', et.box));
    panel.appendChild(mkRow('Analogue Gain (×)', ag.box));
    panel.appendChild(mkRow('Digital Gain (×)', dg.box));
    panel.appendChild(mkRow('Brightness (−1..+1)', bri.box));
    panel.appendChild(mkRow('Contrast (0..2)', con.box));
    panel.appendChild(mkRow('Saturation (0..2)', sat.box));
    panel.appendChild(mkRow('Sharpness (0..2)', sha.box));

    // Insert the sliders panel **after the toolbar**
    toolbar.insertAdjacentElement('afterend', panel);

    // Disable manual fields when AE is on
    function reflectAE() {
      const on = !!ui.ae.checked;
      ui.et.disabled = on;
      ui.ag.disabled = on;
      ui.dg.disabled = on;
    }
    ui.reflectAE = reflectAE;

    // Debounced POST sender
    let timer = null;
    function send(partial) {
      if (timer) clearTimeout(timer);
      timer = setTimeout(async () => {
        try {
          await fetch('/preview_controls', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(partial)
          });
        } catch (e) { }
      }, 120);
    }

    // Wire control events
    ui.ae.addEventListener('change', () => { reflectAE(); send({ AeEnable: ui.ae.checked }); });
    ui.et.addEventListener('input', () => send({ ExposureTime: Number(ui.et.value) }));
    ui.ag.addEventListener('input', () => send({ AnalogueGain: Number(ui.ag.value) }));
    ui.dg.addEventListener('input', () => send({ DigitalGain: Number(ui.dg.value) }));

    ui.bri.addEventListener('input', () => send({ Brightness: Number(ui.bri.value) }));
    ui.con.addEventListener('input', () => send({ Contrast: Number(ui.con.value) }));
    ui.sat.addEventListener('input', () => send({ Saturation: Number(ui.sat.value) }));
    ui.sha.addEventListener('input', () => send({ Sharpness: Number(ui.sha.value) }));

    // Reset handler
    resetBtn.addEventListener('click', async () => {
      try {
        await fetch('/preview_controls', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reset: true })
        });
        await loadPreviewControls(); // refresh UI from server defaults
      } catch (e) { }
    });

    // 📸 Capture image handler
    capBtn.addEventListener('click', async () => {
      capBtn.disabled = true;
      const prevText = capBtn.textContent;
      capBtn.textContent = 'Capturing…';
      capMsg.textContent = '';
      try {
        const r = await fetch('/capture_image', { method: 'POST' });
        const data = await r.json();
        if (!r.ok || !data.ok) {
          capMsg.textContent = 'Failed to capture';
          capMsg.style.color = '#f85149'; // red-ish
        } else {
          const tail = (data.path || '').split(/[\\/]/).pop() || 'image';
          capMsg.textContent = 'Saved: ' + tail;

          // Refresh Files popout if open
          const filesPop = document.getElementById('files-pop');
          if (filesPop && filesPop.classList.contains('open')) {
            const evt = new Event('click');
            document.getElementById('files-toggle')?.dispatchEvent(evt);
            document.getElementById('files-toggle')?.dispatchEvent(evt);
          }
        }
      } catch (e) {
        capMsg.textContent = 'Error capturing';
        capMsg.style.color = '#f85149';
      } finally {
        capBtn.textContent = prevText;
        capBtn.disabled = false;
        setTimeout(() => { capMsg.textContent = ''; capMsg.style.color = ''; }, 2000);
      }
    });
  }

  async function loadPreviewControls() {
    try {
      const res = await fetch('/preview_controls', { cache: 'no-store' });
      const data = await res.json();
      if (!data || !data.ok) return;
      const c = data.controls || {};

      // Fill UI from server values
      if (typeof c.AeEnable === 'boolean') ui.ae.checked = c.AeEnable;

      if (c.ExposureTime != null) ui.et.value = String(c.ExposureTime);
      if (c.AnalogueGain != null) ui.ag.value = String(c.AnalogueGain);
      if (c.DigitalGain != null) ui.dg.value = String(c.DigitalGain);

      ui.bri.value = (c.Brightness ?? 0.0);
      ui.con.value = Math.min(2, (c.Contrast ?? 1.0));
      ui.sat.value = Math.min(2, (c.Saturation ?? 1.0));
      ui.sha.value = Math.min(2, (c.Sharpness ?? 1.0));

      // Update inline labels
      ui.et.dispatchEvent(new Event('input'));
      ui.ag.dispatchEvent(new Event('input'));
      ui.dg.dispatchEvent(new Event('input'));
      ui.bri.dispatchEvent(new Event('input'));
      ui.con.dispatchEvent(new Event('input'));
      ui.sat.dispatchEvent(new Event('input'));
      ui.sha.dispatchEvent(new Event('input'));

      ui.reflectAE && ui.reflectAE();

      if (note) {
        if (data.dev) note.textContent = 'Live MJPEG stream (DEV: camera controls simulated).';
        else note.textContent = 'Live MJPEG stream — changes below apply immediately.';
      }
    } catch (e) { }
  }

  async function startPreview() {
    const dev = await resolveMode();
    ensureControlsUI();

    if (dev) {
      if (feed) feed.style.display = 'none';
      if (cvs) cvs.style.display = '';
      startDevAnim();
    } else {
      if (cvs) { cvs.style.display = 'none'; if (devAnim) { cancelAnimationFrame(devAnim); devAnim = null; } }
      if (feed) {
        feed.style.display = '';
        feed.src = '/preview.mjpg';
      }
    }
    await loadPreviewControls();
  }

  // events
  btn && btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (isOpen()) {
      closePop();
    } else {
      openPop();
      await startPreview();
    }
  });

  document.addEventListener('click', (e) => {
    if (!pop) return;
    if (!pop.contains(e.target) && e.target !== btn) closePop();
  });
})();

// ======================================================
// FILES (popout: list dirs at root, then files inside)
// Adds: Delete + Download buttons per file
// ======================================================
(function () {
  const btn = document.getElementById('files-toggle');
  const pop = document.getElementById('files-pop');
  const list = document.getElementById('files-list');
  const foot = document.getElementById('files-foot');
  const bcEl = document.getElementById('files-bc');

  let currentPath = ""; // relative to CURRENT_SAVE_DIR

  function isOpen() { return pop && pop.classList.contains('open'); }
  function openPop() {
    PanelController.closeAll('files');
    pop.classList.add('open');
    btn && btn.classList.add('active');
    loadPath(""); // root
  }
  function closePop() {
    pop.classList.remove('open');
    btn && btn.classList.remove('active');
  }
  function togglePop() { isOpen() ? closePop() : openPop(); }

  PanelController.register({ files: { close: closePop } });

  function fmtBytes(n) {
    if (n == null || n < 0) return '';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return v.toFixed(v >= 10 ? 0 : 1) + ' ' + u[i];
  }
  function fmtTime(ts) {
    try { return new Date(ts * 1000).toLocaleString(); }
    catch { return ''; }
  }

  function iconForEntry(e) {
    if (e.type === 'dir') {
      return {
        cls: 'folder',
        html: `
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M3.5 7.5h6l1.5 2h9.5v6.5a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2v-6.5a2 2 0 0 1 2-2Z"
                  stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
          </svg>`
      };
    }
    const name = (e.name || '').toLowerCase();
    const ext = name.includes('.') ? name.split('.').pop() : '';

    const videoExt = new Set(['avi', 'mp4', 'mov', 'mkv', 'm4v', 'webm']);
    const imageExt = new Set(['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tif', 'tiff']);

    if (videoExt.has(ext)) {
      return {
        cls: 'video',
        html: `
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M4 7a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7Z"
                  stroke="currentColor" stroke-width="1.6"/>
            <path d="M14 10.5l6-3.5v10l-6-3.5v-3Z"
                  stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
          </svg>`
      };
    }
    if (imageExt.has(ext)) {
      return {
        cls: 'image',
        html: `
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <rect x="3" y="5" width="18" height="14" rx="2"
                  stroke="currentColor" stroke-width="1.6"/>
            <path d="M7 15l3.5-3.5 3 3 2.5-2.5L19 15"
                  stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="9" cy="9" r="1.6" fill="currentColor"/>
          </svg>`
      };
    }
    return {
      cls: 'generic',
      html: `
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M7 3h7l5 5v11a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"
                stroke="currentColor" stroke-width="1.6" />
          <path d="M14 3v5h5" stroke="currentColor" stroke-width="1.6"/>
        </svg>`
    };
  }

  // ---- NEW: Delete helpers (soft delete by default) ----
  async function deletePath(pathRel, permanent = false) {
    const res = await fetch('/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: pathRel, permanent })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  function confirmDelete(pathRel, type) {
    if (!pathRel) return;
    const modal = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-title');
    const msgEl = document.getElementById('confirm-message');
    const okBtn = document.getElementById('confirm-ok');
    const cancel = document.getElementById('confirm-cancel');

    const label = (type === 'dir') ? 'folder' : 'file';
    titleEl.textContent = `Delete ${label}?`;
    msgEl.textContent = `Are you sure you want to delete “${pathRel.split('/').pop()}”?`;

    // open modal
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');

    const onCancel = () => cleanup();
    const onOk = async () => {
      okBtn.disabled = true;
      try {
        await deletePath(pathRel, /*permanent=*/false); // soft delete
        await loadPath(currentPath || '');              // refresh current listing
      } catch (e) {
        alert('Delete failed: ' + e.message);
      } finally {
        okBtn.disabled = false;
        cleanup();
      }
    };
    function cleanup() {
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
      okBtn.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      document.removeEventListener('keydown', onEsc);
    }
    function onEsc(e) { if (e.key === 'Escape') cleanup(); }

    okBtn.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
    document.addEventListener('keydown', onEsc);
  }

  function renderList(data) {
    currentPath = data.path || "";

    // Breadcrumbs
    const parts = currentPath.split('/').filter(Boolean);
    const crumbs = ['<span class="crumb" data-path="">root</span>'];
    let acc = "";
    for (let i = 0; i < parts.length; i++) {
      acc += (i ? "/" : "") + parts[i];
      crumbs.push('<span class="sep">/</span><span class="crumb" data-path="' + acc + '">' + parts[i] + '</span>');
    }
    bcEl.innerHTML = crumbs.join('');

    // At root: show **directories only**.
    // Inside a folder: show dirs first, then files.
    const entries = data.entries || [];
    const atRoot = !currentPath;

    const filtered = atRoot
      ? entries.filter(e => e.type === 'dir')
      : entries; // inside: show all

    list.innerHTML = '';

    if (!filtered.length) {
      const empty = document.createElement('div');
      empty.className = 'file-row';
      empty.innerHTML = '<div class="file-name muted">No items</div>';
      list.appendChild(empty);
    } else {
      for (const e of filtered) {
        const row = document.createElement('div');
        row.className = 'file-row';
        row.dataset.type = e.type;
        row.dataset.path = e.path;

        const ico = document.createElement('div');
        const icon = iconForEntry(e);
        ico.className = 'file-ico ' + icon.cls;
        ico.innerHTML = icon.html;

        const name = document.createElement('div');
        name.className = 'file-name';
        name.textContent = e.name;

        const meta = document.createElement('div');
        meta.className = 'file-meta';
        if (e.type === 'file') {
          const dt = fmtTime(e.mtime || 0);
          meta.textContent = [fmtBytes(e.size), dt].filter(Boolean).join(' • ');
        } else {
          meta.textContent = 'Folder';
        }

        // ---- NEW: row actions (Delete + Download) ----
        const actions = document.createElement('div');
        actions.style.display = 'flex';
        actions.style.gap = '6px';
        actions.style.marginLeft = '8px';

        // Delete (both files & folders)
        const delBtn = document.createElement('button');
        delBtn.className = 'cfg-btn';
        delBtn.textContent = 'Delete';
        delBtn.title = 'Delete';
        delBtn.addEventListener('click', (evt) => {
          evt.stopPropagation();
          confirmDelete(row.dataset.path, row.dataset.type);
        });
        actions.appendChild(delBtn);

        // Download (files only)
        if (e.type === 'file') {
          const a = document.createElement('a');
          a.className = 'cfg-btn';
          a.textContent = 'Download';
          a.title = 'Download';
          a.href = `/media?path=${encodeURIComponent(e.path)}&download=1`;
          a.download = e.name;                 // hint for browsers
          a.addEventListener('click', (ev) => ev.stopPropagation()); // don't open viewer
          actions.appendChild(a);
        }

        row.appendChild(ico);
        row.appendChild(name);
        row.appendChild(meta);
        row.appendChild(actions);
        list.appendChild(row);
      }
    }

    const countDirs = entries.filter(e => e.type === 'dir').length;
    const countFiles = entries.filter(e => e.type === 'file').length;
    foot.textContent = atRoot
      ? `${countDirs} director${countDirs === 1 ? 'y' : 'ies'}`
      : `${countDirs} director${countDirs === 1 ? 'y' : 'ies'} • ${countFiles} file${countFiles === 1 ? '' : 's'}`;
  }

  async function loadPath(pathRel) {
    try {
      const r = await fetch(`/files?path=${encodeURIComponent(pathRel || '')}`, { cache: 'no-store' });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        list.innerHTML = `<div class="file-row"><div class="file-name muted">Error: ${data.error || r.statusText}</div></div>`;
        foot.textContent = '—';
        return;
      }
      renderList(data);
    } catch (e) {
      list.innerHTML = `<div class="file-row"><div class="file-name muted">Error: ${String(e)}</div></div>`;
      foot.textContent = '—';
    }
  }

  // Click handlers
  btn && btn.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePop();
  });
  document.addEventListener('click', (e) => {
    if (!pop) return;
    if (!pop.contains(e.target) && e.target !== btn) closePop();
  });

  // Navigate by clicking rows (dirs navigate; files open viewer)
  list.addEventListener('click', (e) => {
    const row = e.target.closest('.file-row');
    if (!row) return;
    const type = row.dataset.type;
    const path = row.dataset.path || '';
    const name = row.querySelector('.file-name')?.textContent || '';

    if (type === 'dir') {
      loadPath(path);
    } else if (type === 'file') {
      openViewer(path, name);
    }
  });

  // Breadcrumb navigation
  bcEl.addEventListener('click', (e) => {
    const c = e.target.closest('.crumb');
    if (!c) return;
    loadPath(c.dataset.path || '');
  });
})();

function isImageName(name) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  return ['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp', 'tif', 'tiff'].includes(ext);
}
function isVideoName(name) {
  const ext = (name.split('.').pop() || '').toLowerCase();
  return ['mp4', 'webm', 'mov', 'm4v', 'avi', 'mkv'].includes(ext);
}

function openViewer(filePath, fileName) {
  const modal = document.getElementById('viewer-modal');
  const title = document.getElementById('viewer-title');
  const close = document.getElementById('viewer-close');
  const img = document.getElementById('viewer-img');
  const vid = document.getElementById('viewer-video');
  const note = document.getElementById('viewer-note');

  if (!modal || !title || !img || !vid) return;

  title.textContent = fileName || '';
  img.style.display = 'none';
  vid.style.display = 'none';
  vid.removeAttribute('src'); // stop any previous playback
  vid.load();

  const url = `/media?path=${encodeURIComponent(filePath)}`;

  if (isImageName(fileName)) {
    img.src = url;
    img.style.display = '';
    note.textContent = 'Image preview';
  } else if (isVideoName(fileName)) {
    vid.src = url; // Range-supported endpoint
    vid.style.display = '';
    note.textContent = 'Video preview (seeking supported)';
  } else {
    note.textContent = 'This file type is not previewable.';
  }

  modal.classList.add('open');
  modal.setAttribute('aria-hidden', 'false');

  function closeViewer() {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    img.removeAttribute('src');
    vid.pause();
    vid.removeAttribute('src');
    vid.load();
    document.removeEventListener('keydown', escClose);
  }
  function escClose(e) { if (e.key === 'Escape') closeViewer(); }

  close.onclick = closeViewer;
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeViewer();
  });
  document.addEventListener('keydown', escClose);
}

// ======================================================
// LOGGER (popout, read-only)
// ======================================================
(function () {
  const btn = document.getElementById('log-toggle');
  const pop = document.getElementById('log-pop');
  const body = document.getElementById('log-body');
  const meta = document.getElementById('log-meta');
  const refreshBtn = document.getElementById('log-refresh');

  function isOpen() { return pop && pop.classList.contains('open'); }
  function openPop() {
    PanelController.closeAll('log');
    pop.classList.add('open');
    btn && btn.classList.add('active');
    loadLog();
  }
  function closePop() {
    pop.classList.remove('open');
    btn && btn.classList.remove('active');
  }
  function togglePop() { isOpen() ? closePop() : openPop(); }

  PanelController.register({ log: { close: closePop } });

  async function loadLog() {
    try {
      const r = await fetch('/log', { cache: 'no-store' });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        body.textContent = 'Error: ' + (data.error || r.statusText);
        meta.textContent = '—';
        return;
      }
      body.textContent = data.text || '[empty]';
      const started = data.started_ts ? new Date(data.started_ts * 1000).toLocaleString() : '—';
      const sizeKB = Math.round(((data.size || 0) / 1024) * 10) / 10;
      meta.textContent = `File: ${data.path.split(/[\\/]/).pop() || '—'} • Since: ${started} • Reset: ${data.reset_hours}h • Size: ${sizeKB} KB`;
      body.scrollTop = body.scrollHeight;
    } catch (e) {
      body.textContent = 'Error: ' + String(e);
      meta.textContent = '—';
    }
  }

  btn && btn.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePop();
  });
  document.addEventListener('click', (e) => {
    if (!pop) return;
    if (!pop.contains(e.target) && e.target !== btn) closePop();
  });
  refreshBtn && refreshBtn.addEventListener('click', loadLog);
})();

// ======================================================
// Boot
// ======================================================
document.addEventListener('DOMContentLoaded', () => {
  ThemeController.init(); // bind theme toggle immediately
  RefreshController.init();
});

async function boot() {
  await refreshStatus();
  setInterval(refreshStatus, 2000);
  setupWindowChips();
  await tick();
  setInterval(tick, POLL_EVERY_MS);
}
boot();

// Expose functions for HTML buttons
window.startCapture = startCapture;
window.stopCapture = stopCapture;
window.captureStill = captureStill;
