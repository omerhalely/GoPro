// ======================================================
// PiCam Controller — Frontend JS
// ======================================================

// -------- Global Config --------
const POLL_EVERY_MS = 2000;
let   WINDOW_SEC    = 30;
const WINDOW_MS     = () => WINDOW_SEC * 1000;
const MAX_POINTS    = 5000;

// -------- Utilities --------
async function api(path, opts = {}) {
  const r = await fetch(path, { cache: "no-store", ...opts });
  const txt = await r.text();
  try { return JSON.parse(txt) } catch { return { text: txt, status: r.status } }
}
function setDonut(el, pctFree) {
  const clamped = Math.max(0, Math.min(100, pctFree||0));
  el.setAttribute("stroke-dasharray", `${clamped} ${100-clamped}`);
}

// ======================================================
// THEME (Dark/Light) with localStorage
// ======================================================
const ThemeController = (() => {
  const KEY = 'theme'; // 'light' or 'dark'

  function apply(mode) {
    document.body.classList.toggle('light', mode === 'light');
    const icon = document.getElementById('theme-icon');
    if (icon) icon.textContent = (mode === 'light') ? '🌞' : '🌙';
  }

  function load() {
    const stored = localStorage.getItem(KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return 'dark'; // default
  }

  function save(mode) { localStorage.setItem(KEY, mode); }

  function toggle() {
    const current = document.body.classList.contains('light') ? 'light' : 'dark';
    const next = current === 'light' ? 'dark' : 'light';
    apply(next); save(next);
  }

  function init() {
    const mode = load();
    apply(mode);
    const btn = document.getElementById('theme-toggle');
    if (!btn) {
      console.warn('[theme] #theme-toggle not found');
      return;
    }
    btn.addEventListener('click', toggle);
  }

  return { init, toggle };
})();

// ======================================================
// PANELS (mutual exclusivity for power/shell/config)
// ======================================================
const PanelController = (() => {
  let closeShell  = () => {};
  let closeConfig = () => {};
  let closePower  = () => {};

  function register({ shell, config, power }) {
    if (shell  && shell.close)  closeShell  = shell.close;
    if (config && config.close) closeConfig = config.close;
    if (power  && power.close)  closePower  = power.close;
  }
  function closeAll(except = null) {
    if (except !== 'shell')  closeShell();
    if (except !== 'config') closeConfig();
    if (except !== 'power')  closePower();
  }
  return { register, closeAll };
})();

// ======================================================
// STATUS / METRICS / CHARTS
// ======================================================
function setStatus(running, sinceTs){
  const el = document.getElementById('status');
  const cls = running ? 'ok' : 'warn';
  el.className = 'status ' + cls;
  if(running){
    const since = sinceTs ? new Date(sinceTs*1000).toLocaleTimeString() : '—';
    el.innerHTML = '🟢 Recording <span class="mono">(since '+since+')</span>';
  } else {
    el.innerHTML = '🛑 Not recording';
  }
}

async function refreshStatus(){
  const s = await api('/status');
  setStatus(s.running, s.started_ts);
  document.getElementById('save_dir').textContent = s.save_dir ?? '—';
  document.getElementById('disk_path').textContent = s.save_dir ?? '—';
}

async function startCapture(){
  const res = await api('/start');
  document.getElementById('log').textContent = JSON.stringify(res, null, 2);
  refreshStatus();
}

async function stopCapture(){
  const res = await api('/stop');
  document.getElementById('log').textContent = JSON.stringify(res, null, 2);
  setTimeout(refreshStatus, 300);
}

// NEW: capture still image
async function captureStill(){
  const logEl   = document.getElementById('log');
  const timeEl  = document.getElementById('last_image_time');
  const badgeEl = document.getElementById('img_captured_badge');

  try {
    const res  = await fetch('/capture_image', { method: 'POST' });
    const data = await res.json();

    if (!res.ok || !data.ok) {
      // Show a brief error badge
      timeEl.textContent = '—';
      badgeEl.textContent = 'Failed';
      badgeEl.classList.remove('hide');
      badgeEl.classList.add('warn');
      setTimeout(() => { badgeEl.classList.add('hide'); badgeEl.classList.remove('warn'); }, 2000);
      // Optional: keep log minimal
      logEl.textContent = 'Capture failed';
      return;
    }

    // Success: show time + small “Saved” badge
    const now = new Date();
    timeEl.textContent = now.toLocaleTimeString();
    badgeEl.textContent = 'Saved';
    badgeEl.classList.remove('hide');
    setTimeout(() => badgeEl.classList.add('hide'), 1800);

    // Optional: minimal log line (no path)
    logEl.textContent = 'Image captured successfully.';
  } catch (e) {
    timeEl.textContent = '—';
    badgeEl.textContent = 'Error';
    badgeEl.classList.remove('hide');
    badgeEl.classList.add('warn');
    setTimeout(() => { badgeEl.classList.add('hide'); badgeEl.classList.remove('warn'); }, 2000);
    logEl.textContent = 'Error: ' + e;
  }
}

// Ring buffers for charts (timestamped: [t, v])
const buf = { cur:[], vol:[], cpu:[], ram:[], mhz:[] };

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

function drawSparkline(canvas, series, {min=null, max=null} = {}) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width  = canvas.clientWidth  * devicePixelRatio;
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

  // mid grid line
  ctx.globalAlpha = 0.25;
  ctx.strokeStyle = "#2a3346";
  ctx.beginPath();
  const midY = h - pad - (((lo+hi)/2 - lo) / (hi - lo)) * (h - 2*pad);
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
    const x = pad + ((t - t0) / dt) * (w - 2*pad);
    const y = h - pad - ((v - lo) / (hi - lo)) * (h - 2*pad);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

async function tick(){
  const m = await api('/metrics');
  const now = performance.now();

  document.getElementById('cpu_temp').innerHTML = (m.cpu.temp_c ?? '—') + '<span class="unit">°C</span>';
  document.getElementById('gpu_temp').innerHTML = (m.gpu.temp_c ?? '—') + '<span class="unit">°C</span>';
  document.getElementById('disk_free').innerHTML = (m.disk.free_pct ?? '—') + '<span class="unit">%</span>';
  setDonut(document.getElementById('donut'), m.disk.free_pct ?? 0);

  push('cur', m.sensors.current_a, now);
  push('vol', m.sensors.voltage_v, now);
  push('cpu', m.cpu.util_pct,      now);
  push('ram', m.ram.used_pct,      now);
  push('mhz', m.cpu.freq_mhz,      now);

  document.getElementById('cur_now').textContent = m.sensors.current_a ?? '—';
  document.getElementById('vol_now').textContent = m.sensors.voltage_v ?? '—';
  document.getElementById('cpu_now').textContent = m.cpu.util_pct ?? '—';
  document.getElementById('ram_now').textContent = m.ram.used_pct ?? '—';
  document.getElementById('mhz_now').textContent = m.cpu.freq_mhz ?? '—';

  drawSparkline(document.getElementById('cur'), buf.cur, {min:0});
  drawSparkline(document.getElementById('vol'), buf.vol);
  drawSparkline(document.getElementById('cpu'), buf.cpu, {min:0, max:100});
  drawSparkline(document.getElementById('ram'), buf.ram, {min:0, max:100});
  drawSparkline(document.getElementById('mhz'), buf.mhz);
}

// Window chip controls
function setupWindowChips() {
  const allChips = Array.from(document.querySelectorAll('.chip'));
  function activate(sec) {
    WINDOW_SEC = Number(sec);
    allChips.forEach(c => {
      c.classList.toggle('active', Number(c.dataset.win) === WINDOW_SEC);
    });
    Object.values(buf).forEach(prune);
    drawSparkline(document.getElementById('cur'), buf.cur, {min:0});
    drawSparkline(document.getElementById('vol'), buf.vol);
    drawSparkline(document.getElementById('cpu'), buf.cpu, {min:0, max:100});
    drawSparkline(document.getElementById('ram'), buf.ram, {min:0, max:100});
    drawSparkline(document.getElementById('mhz'), buf.mhz);
  }
  allChips.forEach(chip => {
    chip.addEventListener('click', () => activate(chip.dataset.win));
  });
  activate(document.querySelector('.chip.active')?.dataset.win ?? 30);
}

// ======================================================
// SHELL Drawer (exclusive + cls clear)
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

  // expose to PanelController
  PanelController.register({ shell: { close: closeDrawer } });

  function appendOut(kind, text) {
    const prefix = kind === 'stdout' ? '' : '[stderr] ';
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
// CONFIG Drawer (exclusive + live apply + LED no-op)
// ======================================================
(function () {
  const drawer = document.getElementById('config-drawer');
  const toggle = document.getElementById('config-toggle');

  const saveDirInput = document.getElementById('cfg-save-dir');
  const saveDirReset = document.getElementById('cfg-save-dir-reset');
  const ledToggle = document.getElementById('cfg-led');
  const modeNote = document.getElementById('cfg-mode-note');
  const ledNote = document.getElementById('cfg-led-note');

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

  // expose for PanelController
  PanelController.register({ config: { close: closeDrawer } });

  async function loadConfig() {
    const cfg = await (await fetch('/config', {cache:'no-store'})).json();
    saveDirInput.value = cfg.save_dir_current || '';
    modeNote.textContent = cfg.development_mode ? 'DEV mode' : 'PROD';
    ledToggle.checked = !!cfg.led_on;
    ledNote.textContent = cfg.development_mode ? ' (no-op in DEV)' : '';
    document.getElementById('save_dir').textContent = cfg.save_dir_current ?? '—';
    document.getElementById('disk_path').textContent = cfg.save_dir_current ?? '—';
  }

  // Debounced auto-apply when typing
  let applyTimer = null;
  function scheduleApplyPath() {
    if (applyTimer) clearTimeout(applyTimer);
    applyTimer = setTimeout(async () => {
      const path = saveDirInput.value.trim();
      await fetch('/config', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ save_dir: path })
      });
      refreshStatus();
    }, 300);
  }

  async function restoreDefault() {
    const r = await fetch('/config', {cache:'no-store'});
    const cfg = await r.json();
    saveDirInput.value = cfg.save_dir_default || '';
    scheduleApplyPath();
  }

  async function applyLed() {
    await fetch('/config', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ led_on: !!ledToggle.checked })
    });
  }

  toggle.addEventListener('click', async () => {
    toggleDrawer();
    if (isOpen()) await loadConfig();
  });
  saveDirInput.addEventListener('input', scheduleApplyPath);
  saveDirReset.addEventListener('click', restoreDefault);
  ledToggle.addEventListener('change', applyLed);
})();

// ======================================================
// POWER (popover + confirm) — exclusive
// ======================================================
(function () {
  const btn = document.getElementById('power-toggle');
  const pop = document.getElementById('power-pop');

  function isOpen(){ return pop.classList.contains('open'); }
  function openPop() {
    PanelController.closeAll('power');
    pop.classList.add('open');
    btn.classList.add('active');
  }
  function closePop() {
    pop.classList.remove('open');
    btn.classList.remove('active');
  }
  function togglePop() { isOpen() ? closePop() : openPop(); }

  // expose close for PanelController
  PanelController.register({ power: { close: closePop } });

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePop();
  });

  document.addEventListener('click', (e) => {
    if (!pop.contains(e.target) && e.target !== btn) closePop();
  });

  pop.addEventListener('click', async (e) => {
    const el = e.target.closest('button[data-action]');
    if (!el) return;
    const action = el.getAttribute('data-action');
    const label = action === 'reboot' ? 'restart' : 'shut down';
    const ok = window.confirm(`Are you sure you want to ${label} the Raspberry Pi?`);
    if (!ok) return;
    closePop();
    try {
      const r = await fetch('/power', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action })
      });
      const data = await r.json();
      if (!r.ok || !data.ok) {
        alert('Failed: ' + (data && (data.error || data.message) || r.statusText));
      } else {
        alert(data.message || 'Command sent.');
      }
    } catch (err) {
      alert('Error: ' + err);
    }
  });
})();

// ======================================================
// BOOT
// ======================================================
document.addEventListener('DOMContentLoaded', () => {
  ThemeController.init(); // ensure theme toggle is bound asap
});

async function boot(){
  await refreshStatus();
  setInterval(refreshStatus, 2000);
  setupWindowChips();
  await tick();
  setInterval(tick, POLL_EVERY_MS);
}
boot();

// Expose functions for HTML buttons
window.startCapture = startCapture;
window.stopCapture  = stopCapture;
window.captureStill = captureStill;
