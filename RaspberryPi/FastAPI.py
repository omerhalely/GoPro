from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import threading, time, os, subprocess

app = FastAPI()

# ── Settings ──────────────────────────────────────────────────────────────────
DEFAULT_SAVE_DIR = "/home/pi/Videos/frames"   # fixed output directory

# ── DEV toggle ────────────────────────────────────────────────────────────────
DEVELOPMENT_MODE = True  # ← set False on the Raspberry Pi

# ── Shell console settings ────────────────────────────────────────────────────
SHELL_ENABLED = True               # ⚠️ Anyone with page access can run commands
SHELL_TIMEOUT_DEFAULT = 15         # seconds
SHELL_MAX_CHARS = 100_000          # cap combined stdout/stderr size

# Tiny random float without importing random
def randf(lo, hi):
    r = int.from_bytes(os.urandom(8), "big") / (1 << 64)
    return lo + (hi - lo) * r

# ── Global state ──────────────────────────────────────────────────────────────
_state_lock = threading.Lock()
_is_running = False
_stop_evt = threading.Event()
_capture_thread = None
_last_start_ts = None

# CPU utilization bookkeeping (only used when not in DEV)
_prev_total = None
_prev_idle  = None

# ── Capture thread runner (stub while developing) ─────────────────────────────
def _run_capture_thread():
    global _is_running
    try:
        # video_capture(_stop_evt)  # plug in later on the Pi
        print("Capture Video")
        while not _stop_evt.is_set():
            time.sleep(0.25)
    finally:
        with _state_lock:
            _is_running = False
        _stop_evt.clear()

# ── System metrics (DEV stubs + real on Pi) ───────────────────────────────────
def _read_cpu_temp_c():
    if DEVELOPMENT_MODE:
        return round(randf(38.0, 72.0), 1)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return float(f.read().strip()) / 1000.0
    except Exception:
        return None

def _read_gpu_temp_c():
    if DEVELOPMENT_MODE:
        return round(randf(40.0, 70.0), 1)
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"], text=True, timeout=1)
        if "temp=" in out:
            return float(out.split("temp=")[1].split("'")[0])
    except Exception:
        pass
    return None

def _read_cpu_util_percent():
    if DEVELOPMENT_MODE:
        base = randf(8.0, 35.0)
        spike = randf(0, 1)
        return round(base + (50.0 if spike > 0.95 else 0.0), 1)
    global _prev_total, _prev_idle
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return None
        parts = [float(x) for x in line.split()[1:11]]
        user, nice, system, idle, iowait, irq, softirq, steal, *_ = (parts + [0]*10)[:8]
        idle_all = idle + iowait
        non_idle = user + nice + system + irq + softirq + steal
        total = idle_all + non_idle
        if _prev_total is None:
            _prev_total, _prev_idle = total, idle_all
            return None
        totald = total - _prev_total
        idled  = idle_all - _prev_idle
        _prev_total, _prev_idle = total, idle_all
        if totald <= 0:
            return None
        return max(0.0, min(100.0, (totald - idled) * 100.0 / totald))
    except Exception:
        return None

def _read_ram_percent_used():
    if DEVELOPMENT_MODE:
        return round(randf(20.0, 85.0), 1)
    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                meminfo[k] = float(v.strip().split()[0])  # kB
        total = meminfo.get("MemTotal")
        avail = meminfo.get("MemAvailable")
        if not total or not avail:
            return None
        used = total - avail
        return used * 100.0 / total
    except Exception:
        return None

def _read_disk_free_percent(path):
    if DEVELOPMENT_MODE:
        return round(randf(35.0, 95.0), 1)
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free  = st.f_bavail * st.f_frsize
        if total <= 0:
            return None
        return free * 100.0 / total
    except Exception:
        return None

def _read_cpu_freq_mhz():
    if DEVELOPMENT_MODE:
        return round(randf(600.0, 1500.0), 0)
    for p in (
        "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
        "/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq",
    ):
        try:
            with open(p) as f:
                v = f.read().strip()
                return (int(v) if v.isdigit() else float(v)) / 1000.0
        except Exception:
            continue
    return None

def _read_voltage_current():
    if DEVELOPMENT_MODE:
        volts = round(randf(4.80, 5.20), 3)
        amps  = round(randf(0.10, 2.50), 3)
        return amps, volts
    try:
        # TODO: implement sensor reads on the Pi (e.g., INA219/INA260)
        return None, None
    except Exception:
        return None, None

# ── API endpoints (capture) ───────────────────────────────────────────────────
@app.get("/start")
def start_capture():
    global _capture_thread, _is_running, _last_start_ts
    with _state_lock:
        if _is_running:
            raise HTTPException(status_code=409, detail="Capture already running")
        _stop_evt.clear()
        _is_running = True
        _last_start_ts = int(time.time())
        _capture_thread = threading.Thread(target=_run_capture_thread, daemon=True)
        _capture_thread.start()
    return {"status": "started", "started_ts": _last_start_ts, "save_dir": DEFAULT_SAVE_DIR}

@app.get("/stop")
def stop_capture():
    _stop_evt.set()
    return {"status": "stop signaled"}

@app.get("/status")
def status():
    with _state_lock:
        return {"running": _is_running, "started_ts": _last_start_ts, "save_dir": DEFAULT_SAVE_DIR}

# ── API endpoint: live metrics ────────────────────────────────────────────────
@app.get("/metrics")
def metrics():
    ts = time.time()
    cpu_temp = _read_cpu_temp_c()
    gpu_temp = _read_gpu_temp_c()
    cpu_util = _read_cpu_util_percent()
    ram_used = _read_ram_percent_used()
    disk_free = _read_disk_free_percent(DEFAULT_SAVE_DIR)
    cpu_mhz = _read_cpu_freq_mhz()
    amps, volts = _read_voltage_current()

    def rnd(x, n=2): return None if x is None else round(x, n)
    return JSONResponse({
        "ts": ts,
        "sensors": {
            "current_a": rnd(amps, 3),
            "voltage_v": rnd(volts, 3),
        },
        "cpu": {
            "temp_c": rnd(cpu_temp, 1),
            "util_pct": rnd(cpu_util, 1),
            "freq_mhz": rnd(cpu_mhz, 0),
        },
        "gpu": {
            "temp_c": rnd(gpu_temp, 1),
        },
        "ram": {
            "used_pct": rnd(ram_used, 1),
        },
        "disk": {
            "free_pct": rnd(disk_free, 1),
            "path": DEFAULT_SAVE_DIR,
        }
    })

# ── API endpoint: shell command execution ─────────────────────────────────────
@app.post("/shell")
async def run_shell(req: Request):
    if not SHELL_ENABLED:
        raise HTTPException(status_code=403, detail="Shell disabled on server")

    try:
        body = await req.json()
    except Exception:
        body = {}

    cmd = (body.get("cmd") or "").strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Missing 'cmd'")

    timeout = body.get("timeout") or SHELL_TIMEOUT_DEFAULT
    try:
        timeout = max(1, min(int(timeout), 300))  # 1..300s
    except Exception:
        timeout = SHELL_TIMEOUT_DEFAULT

    start = time.time()
    try:
        res = subprocess.run(
            ["bash", "-lc", cmd],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        out = out[:SHELL_MAX_CHARS]
        return JSONResponse({
            "ok": False,
            "timeout": True,
            "code": None,
            "elapsed_sec": round(time.time() - start, 3),
            "stdout": (e.stdout or "")[:SHELL_MAX_CHARS],
            "stderr": (e.stderr or "")[:SHELL_MAX_CHARS],
            "ran": cmd,
        }, status_code=504)

    # Truncate big outputs
    stdout = (res.stdout or "")[:SHELL_MAX_CHARS]
    stderr = (res.stderr or "")[:SHELL_MAX_CHARS]

    return {
        "ok": res.returncode == 0,
        "code": res.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout": stdout,
        "stderr": stderr,
        "ran": cmd,
    }

# ── Web UI (no f-string; JS fills dynamic fields) ────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    html = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PiCam Controller</title>
<style>
  :root { color-scheme: dark; }
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;
       background:#0f1115;color:#e6e6e6;min-height:100vh}
  .wrap{max-width:1100px;margin:0 auto;padding:18px}
  .row{display:grid;grid-template-columns:1fr;gap:14px}
  @media(min-width:1200px){ .row{grid-template-columns:1fr 1fr} }
  .card{border-radius:18px;background:#161a23;box-shadow:0 10px 30px rgba(0,0,0,.4);padding:18px}
  h1{margin:8px 0 8px;font-size:26px}
  h2{margin:8px 0 14px;font-size:18px;opacity:.9;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .status{padding:10px 12px;border-radius:12px;margin:8px 0;font-weight:600}
  .ok{background:#0e3a1f;color:#bff5cf;border:1px solid #1f6b3a}
  .warn{background:#3a1e0e;color:#ffd9bf;border:1px solid #6b3b1f}
  .btn{font-size:18px;font-weight:700;padding:12px;border-radius:12px;border:none;cursor:pointer}
  .start{background:#1e784d;color:white}
  .stop{background:#a12a2a;color:white}
  .muted{opacity:.8;font-size:13px}
  .mono{font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .tile{background:#0f131c;border:1px solid #263049;border-radius:14px;padding:12px}
  .kpi{font-size:22px;font-weight:700}
  .unit{opacity:.7;font-size:12px;margin-left:4px}
  .canvasBox{height:90px}
  canvas.spark{width:100%;height:90px;display:block}
  .donut{display:flex;align-items:center;gap:14px}
  .donut svg{width:80px;height:80px}
  .footer{margin-top:18px;opacity:.7;font-size:12px;text-align:center}
  .small{font-size:12px;opacity:.8}

  /* Window selector chips */
  .chips{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  .chip{padding:6px 10px;border-radius:999px;border:1px solid #2a3550;background:#0f131c;cursor:pointer;font-size:12px}
  .chip.active{background:#1b2334;border-color:#5b7cfa;box-shadow:0 0 0 1px rgba(91,124,250,.35) inset}

  /* Shell */
  .shell-grid{display:grid;grid-template-columns:1fr;gap:10px}
  .shell-in{width:100%;min-height:110px;border-radius:12px;border:1px solid #2a3550;background:#0f131c;color:#e6e6e6;padding:10px;font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace}
  .shell-run{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .shell-out{white-space:pre-wrap;background:#0f131c;border:1px solid #2a3550;border-radius:12px;padding:12px;max-height:300px;overflow:auto}
  .inline{display:inline-block}
  .input{border-radius:10px;border:1px solid #2a3550;background:#0f131c;color:#e6e6e6;padding:8px}
</style>
</head>
<body>
<div class="wrap">
  <h1>🎥 PiCam Controller</h1>

  <div class="row">
    <div class="card">
      <h2>Controls</h2>
      <div id="status" class="status warn">Checking status…</div>
      <div class="grid2">
        <button class="btn start" onclick="start()">START</button>
        <button class="btn stop"  onclick="stop()">STOP</button>
      </div>
      <div class="muted small">Saving to: <span class="mono" id="save_dir">—</span></div>
      <pre class="muted mono" id="log"></pre>
      <div class="footer small">Software-stop only • Non-blocking capture thread</div>
    </div>

    <div class="card">
      <h2>Temperatures & Storage</h2>
      <div class="grid2">
        <div class="tile">
          <div>CPU Temp</div>
          <div class="kpi" id="cpu_temp">—<span class="unit">°C</span></div>
        </div>
        <div class="tile">
          <div>GPU Temp</div>
          <div class="kpi" id="gpu_temp">—<span class="unit">°C</span></div>
        </div>
        <div class="tile donut">
          <svg viewBox="0 0 36 36">
            <defs>
              <linearGradient id="grad"><stop offset="0%" stop-color="#2dd4bf"/><stop offset="100%" stop-color="#60a5fa"/></linearGradient>
            </defs>
            <path d="M18 2 a16 16 0 1 1 0 32 a16 16 0 1 1 0 -32" fill="none" stroke="#1f2633" stroke-width="4"/>
            <path id="donut" d="M18 2 a16 16 0 1 1 0 32 a16 16 0 1 1 0 -32"
                  fill="none" stroke="url(#grad)" stroke-width="4" stroke-linecap="round"
                  stroke-dasharray="0 100"/>
          </svg>
          <div>
            <div class="kpi" id="disk_free">—<span class="unit">%</span></div>
            <div class="small">Free on <span class="mono" id="disk_path">—</span></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="row" style="margin-top:14px">
    <div class="card">
      <h2>
        Power
        <span class="chips">
          <span class="muted small">Window:</span>
          <button class="chip active" data-win="30">30s</button>
          <button class="chip" data-win="60">1m</button>
          <button class="chip" data-win="300">5m</button>
        </span>
      </h2>
      <div class="grid2">
        <div class="tile">
          <div>Current (A)</div>
          <div class="canvasBox"><canvas id="cur" class="spark"></canvas></div>
          <div class="small">Live: <span id="cur_now">—</span> A</div>
        </div>
        <div class="tile">
          <div>Voltage (V)</div>
          <div class="canvasBox"><canvas id="vol" class="spark"></canvas></div>
          <div class="small">Live: <span id="vol_now">—</span> V</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>
        System
        <span class="chips">
          <span class="muted small">Window:</span>
          <button class="chip active" data-win="30">30s</button>
          <button class="chip" data-win="60">1m</button>
          <button class="chip" data-win="300">5m</button>
        </span>
      </h2>
      <div class="grid2">
        <div class="tile">
          <div>CPU Utilization (%)</div>
          <div class="canvasBox"><canvas id="cpu" class="spark"></canvas></div>
          <div class="small">Live: <span id="cpu_now">—</span>%</div>
        </div>
        <div class="tile">
          <div>RAM Used (%)</div>
          <div class="canvasBox"><canvas id="ram" class="spark"></canvas></div>
          <div class="small">Live: <span id="ram_now">—</span>%</div>
        </div>
        <div class="tile" style="grid-column: span 2">
          <div>CPU Clock (MHz)</div>
          <div class="canvasBox"><canvas id="mhz" class="spark"></canvas></div>
          <div class="small">Live: <span id="mhz_now">—</span> MHz</div>
        </div>
      </div>
    </div>
  </div>

  <!-- Shell console -->
  <div class="row" style="margin-top:14px">
    <div class="card">
      <h2>Shell (server)</h2>
      <div class="muted small">Runs on the Raspberry Pi / server. Be careful — full shell access.</div>
      <div class="shell-grid">
        <textarea id="sh_cmd" class="shell-in" placeholder="e.g., uname -a"></textarea>
        <div class="shell-run">
          <label class="muted small inline">Timeout (s):</label>
          <input id="sh_timeout" type="number" class="input inline" value="15" min="1" max="300" style="width:80px">
          <button id="sh_run_btn" class="btn start inline" onclick="runShell()">Run</button>
        </div>
        <div class="tile">
          <div class="small muted">Output</div>
          <pre id="sh_out" class="shell-out"></pre>
        </div>
      </div>
    </div>
  </div>

</div>

<script>
// ====== CONFIG ======
const POLL_EVERY_MS = 2000;       // /metrics poll period
let   WINDOW_SEC    = 30;         // default window (chips control it)
const WINDOW_MS     = () => WINDOW_SEC * 1000;
const MAX_POINTS    = 5000;       // safety cap

// ====== RING BUFFERS (timestamped: [t, v]) ======
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

// ====== SPARKLINE (time-based X scale) ======
function drawSparkline(canvas, series, {min=null, max=null} = {}) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width  = canvas.clientWidth  * devicePixelRatio;
  const h = canvas.height = canvas.clientHeight * devicePixelRatio;
  ctx.clearRect(0, 0, w, h);
  if (!series.length) return;

  const now = performance.now();
  const t0 = Math.min(series[0][0], now - WINDOW_MS());
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

function setDonut(el, pctFree) {
  const clamped = Math.max(0, Math.min(100, pctFree||0));
  el.setAttribute("stroke-dasharray", `${clamped} ${100-clamped}`);
}

async function api(path, opts={}) {
  const r = await fetch(path, {cache:'no-store', ...opts});
  const txt = await r.text();
  try { return JSON.parse(txt) } catch { return {text: txt, status: r.status} }
}

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

async function start(){
  const res = await api('/start');
  document.getElementById('log').textContent = JSON.stringify(res, null, 2);
  refreshStatus();
}

async function stop(){
  const res = await api('/stop');
  document.getElementById('log').textContent = JSON.stringify(res, null, 2);
  setTimeout(refreshStatus, 300);
}

async function tick(){
  const m = await api('/metrics');
  const now = performance.now();

  // KPIs
  document.getElementById('cpu_temp').innerHTML = (m.cpu.temp_c ?? '—') + '<span class="unit">°C</span>';
  document.getElementById('gpu_temp').innerHTML = (m.gpu.temp_c ?? '—') + '<span class="unit">°C</span>';
  document.getElementById('disk_free').innerHTML = (m.disk.free_pct ?? '—') + '<span class="unit">%</span>';
  setDonut(document.getElementById('donut'), m.disk.free_pct ?? 0);

  // buffers (timestamped)
  push('cur', m.sensors.current_a, now);
  push('vol', m.sensors.voltage_v, now);
  push('cpu', m.cpu.util_pct,      now);
  push('ram', m.ram.used_pct,      now);
  push('mhz', m.cpu.freq_mhz,      now);

  // now values
  document.getElementById('cur_now').textContent = m.sensors.current_a ?? '—';
  document.getElementById('vol_now').textContent = m.sensors.voltage_v ?? '—';
  document.getElementById('cpu_now').textContent = m.cpu.util_pct ?? '—';
  document.getElementById('ram_now').textContent = m.ram.used_pct ?? '—';
  document.getElementById('mhz_now').textContent = m.cpu.freq_mhz ?? '—';

  // draw (time-windowed)
  drawSparkline(document.getElementById('cur'), buf.cur, {min:0});
  drawSparkline(document.getElementById('vol'), buf.vol);
  drawSparkline(document.getElementById('cpu'), buf.cpu, {min:0, max:100});
  drawSparkline(document.getElementById('ram'), buf.ram, {min:0, max:100});
  drawSparkline(document.getElementById('mhz'), buf.mhz);
}

// ====== Window chips logic ======
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

// ====== Shell runner ======
async function runShell() {
  const btn = document.getElementById('sh_run_btn');
  const cmd = (document.getElementById('sh_cmd').value || '').trim();
  const timeout = parseInt(document.getElementById('sh_timeout').value || '15', 10);
  const outEl = document.getElementById('sh_out');

  if (!cmd) return;

  btn.disabled = true;
  outEl.textContent = 'Running: ' + cmd + '\\n\\n';

  try {
    const res = await fetch('/shell', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cmd, timeout })
    });
    const data = await res.json();
    let text = '';
    text += `$ ${cmd}\\n\\n`;
    if (data.stdout) text += data.stdout;
    if (data.stderr) text += (data.stdout ? '\\n' : '') + data.stderr;
    text += (text.endsWith('\\n') ? '' : '\\n');
    text += `\\n[exit=${data.code ?? '—'} ok=${data.ok} elapsed=${data.elapsed_sec ?? '—'}s${data.timeout ? ' TIMEOUT' : ''}]`;
    outEl.textContent = text;
  } catch (e) {
    outEl.textContent += '\\nError: ' + (e && e.message ? e.message : e);
  } finally {
    btn.disabled = false;
  }
}

// Boot
refreshStatus();
setInterval(refreshStatus, 2000);
setupWindowChips();
tick();
setInterval(tick, POLL_EVERY_MS);
</script>
</body>
</html>
    """
    return HTMLResponse(content=html)

# Optional: run with `python3 main.py`
if __name__ == "__main__":
    import uvicorn
    # Replace "main:app" with "<your_filename_without_py>:app" if you rename this file
    uvicorn.run("FastAPI:app", host="0.0.0.0", port=8000)
