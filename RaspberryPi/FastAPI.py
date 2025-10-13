from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
import threading, time, os, subprocess, platform

app = FastAPI()

# ── Settings ──────────────────────────────────────────────────────────────────
DEFAULT_SAVE_DIR = "/home/pi/Videos/frames"   # fixed default output directory

# ── DEV toggle ────────────────────────────────────────────────────────────────
DEVELOPMENT_MODE = True  # ← set False on the Raspberry Pi for real actions

# ── Shell console settings ────────────────────────────────────────────────────
SHELL_ENABLED = True               # ⚠️ Anyone with page access can run commands
SHELL_TIMEOUT_DEFAULT = 15         # seconds
SHELL_MAX_CHARS = 100_000          # cap combined stdout/stderr size

# ── Mutable runtime config (server-side) ──────────────────────────────────────
CURRENT_SAVE_DIR = DEFAULT_SAVE_DIR
LED_ON = False   # tracked state; no-op in DEVELOPMENT_MODE

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
        # video_capture(_stop_evt, output_dir=CURRENT_SAVE_DIR)  # plug in on the Pi
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

def _set_led(on: bool):
    global LED_ON
    LED_ON = bool(on)
    if DEVELOPMENT_MODE:
        return
    try:
        # TODO: implement GPIO control here (e.g., RPi.GPIO or gpiozero)
        pass
    except Exception:
        pass

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
    return {"status": "started", "started_ts": _last_start_ts, "save_dir": CURRENT_SAVE_DIR}

@app.get("/stop")
def stop_capture():
    _stop_evt.set()
    return {"status": "stop signaled"}

@app.get("/status")
def status():
    with _state_lock:
        return {"running": _is_running, "started_ts": _last_start_ts, "save_dir": CURRENT_SAVE_DIR}

# ── Config endpoints ──────────────────────────────────────────────────────────
@app.get("/config")
def get_config():
    return {
        "save_dir_current": CURRENT_SAVE_DIR,
        "save_dir_default": DEFAULT_SAVE_DIR,
        "led_on": LED_ON,
        "development_mode": DEVELOPMENT_MODE,
    }

@app.post("/config")
async def update_config(req: Request):
    global CURRENT_SAVE_DIR
    try:
        body = await req.json()
    except Exception:
        body = {}

    updated = {}

    # save_dir update (if provided)
    save_dir = body.get("save_dir")
    if isinstance(save_dir, str) and save_dir.strip():
        CURRENT_SAVE_DIR = save_dir.strip()
        updated["save_dir_current"] = CURRENT_SAVE_DIR

    # led_on update (if provided)
    if "led_on" in body:
        _set_led(bool(body.get("led_on")))
        updated["led_on"] = LED_ON

    # Return full config after update
    cfg = get_config()
    cfg["updated"] = updated
    return cfg

# ── Power endpoint (restart/shutdown) ─────────────────────────────────────────
@app.post("/power")
async def power_action(req: Request):
    """
    Body: {"action": "reboot" | "shutdown"}
    DEV mode: simulate only.
    PROD: run real commands (requires sudo privileges).
    """
    try:
        body = await req.json()
    except Exception:
        body = {}
    action = (body.get("action") or "").lower()
    if action not in ("reboot", "shutdown"):
        raise HTTPException(status_code=400, detail="Invalid action (use 'reboot' or 'shutdown')")

    if DEVELOPMENT_MODE:
        return {"ok": True, "dev": True, "action": action, "message": f"Simulated {action} in DEV mode."}

    try:
        if action == "reboot":
            cmd = ["sudo", "reboot"]
        else:
            cmd = ["sudo", "shutdown", "-h", "now"]
        subprocess.Popen(cmd)  # don't wait; system may terminate the process
        return {"ok": True, "dev": False, "action": action, "message": f"{action} command sent."}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

# ── API endpoint: live metrics ────────────────────────────────────────────────
@app.get("/metrics")
def metrics():
    ts = time.time()
    cpu_temp = _read_cpu_temp_c()
    gpu_temp = _read_gpu_temp_c()
    cpu_util = _read_cpu_util_percent()
    ram_used = _read_ram_percent_used()
    disk_free = _read_disk_free_percent(CURRENT_SAVE_DIR)
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
            "path": CURRENT_SAVE_DIR,
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
    os_name = platform.system().lower()
    try:
        if "windows" in os_name:
            exec_cmd = ["cmd", "/c", cmd]
            res = subprocess.run(
                exec_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="oem",
                errors="replace",
            )
        else:
            exec_cmd = ["bash", "-lc", cmd]
            res = subprocess.run(
                exec_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
        elapsed = time.time() - start
    except subprocess.TimeoutExpired as e:
        return JSONResponse({
            "ok": False,
            "timeout": True,
            "code": None,
            "elapsed_sec": round(time.time() - start, 3),
            "stdout": (e.stdout or "")[:SHELL_MAX_CHARS],
            "stderr": (e.stderr or "")[:SHELL_MAX_CHARS],
            "ran": exec_cmd if 'exec_cmd' in locals() else cmd,
        }, status_code=504)

    stdout = (res.stdout or "")[:SHELL_MAX_CHARS]
    stderr = (res.stderr or "")[:SHELL_MAX_CHARS]

    return {
        "ok": res.returncode == 0,
        "code": res.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout": stdout,
        "stderr": stderr,
        "ran": exec_cmd,
    }

# ── Web UI ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    html = """
<!doctype html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PiCam Controller</title>
<style>
  :root {
    color-scheme: dark;
    --rail-w: 70px;                 /* width of the right rail */
  }

  /* Base layout */
  body{
    margin:0;
    font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,Arial;
    background:#0f1115;color:#e6e6e6;min-height:100vh
  }
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

  /* ===== Right-side Rail (vertical line menu) ===== */
  #right-rail{
    position:fixed; top:0; right:0;
    width:var(--rail-w); height:100vh;
    z-index:10000;
    display:flex; flex-direction:column; align-items:center;
    gap:12px; padding:12px 9px;
    border-left:1px solid #1f2328; /* the vertical divider */
    background:transparent;
  }
  .fab{
    width:52px; height:52px; border-radius:50%;
    border:none; cursor:pointer; background:#111; color:#fff;
    display:grid; place-items:center;
    box-shadow:0 8px 24px rgba(0,0,0,.25);
  }
  .fab.active{ background:#1a1f2a; outline:1px solid #333; }

  /* Small popover for power actions */
  #power-pop{
    position: fixed;
    top: 12px; right: calc(var(--rail-w) + 10px);
    background:#0b0d10; border:1px solid #1f2328; border-radius:10px;
    box-shadow:0 12px 30px rgba(0,0,0,.35);
    padding:8px; display:none; z-index:10001;
  }
  #power-pop.open{ display:block; }
  #power-pop button{
    display:block; width:100%; text-align:left; padding:8px 10px; margin:0;
    background:#12151b; color:#e6e6e6; border:1px solid #2b3138; border-radius:8px; cursor:pointer;
  }
  #power-pop button + button{ margin-top:6px; }
  #power-pop button:hover{ background:#161a20; }

  /* ===== Drawers (open to the LEFT of the rail) ===== */
  .drawer{
    position:fixed; top:0; right:var(--rail-w);
    height:100vh; width:min(520px, calc(90vw - var(--rail-w)));
    background:#0b0d10; color:#e6e6e6;

    /* closed state: fully hidden & non-interactive */
    transform:translateX(100%);
    visibility:hidden;
    opacity:0;
    pointer-events:none;
    box-shadow:none;
    border-left:none;

    transition:transform .28s ease, opacity .18s ease;
    z-index:9998; display:flex; flex-direction:column;
    box-sizing:border-box;  /* predictable sizing */
  }
  .drawer.open{
    transform:translateX(0%);
    visibility:visible;
    opacity:1;
    pointer-events:auto;
    box-shadow:-24px 0 48px rgba(0,0,0,.35);
    border-left:1px solid #1f2328;
  }

  /* Header & rows: add right padding so buttons don't hug divider; align center */
  .shell-head,.cfg-head{
    display:flex; align-items:center; gap:12px;
    padding:14px 16px; padding-right:28px;
    border-bottom:1px solid #1f2328;
  }
  .shell-actions,.cfg-actions{
    margin-left:auto; display:flex; gap:8px; align-items:center;
  }

  .shell-btn,.cfg-btn{ background:#161a20; color:#c9d1d9; border:1px solid #2b3138; padding:6px 10px; border-radius:6px; cursor:pointer; }
  .shell-inp{ flex:1; background:#0e1116; color:#e6e6e6; border:1px solid #2b3138; border-radius:8px; padding:10px 12px; outline:none; }
  .shell-run{ background:#238636; color:#fff; border:1px solid #2ea043; padding:10px 14px; border-radius:8px; cursor:pointer; line-height:1; }

  .shell-row{
    padding:12px 16px; padding-right:28px;
    display:flex; gap:8px; align-items:center;
    border-bottom:1px solid #1f2328;
  }
  .shell-out{
    flex:1; margin:0; padding:14px 16px; overflow:auto; white-space:pre-wrap; word-break:break-word;
    font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  }
  .shell-status{ padding:8px 16px; font-size:12px; color:#9da7b3; border-top:1px solid #1f2328; }

  /* Config drawer content */
  .cfg-row{ padding:12px 16px; border-bottom:1px solid #1f2328; }
  .cfg-label{ font-size:13px; opacity:.9; margin-bottom:8px; }
  .cfg-flex{ display:flex; gap:8px; align-items:center; }
  .cfg-inp{ flex:1; background:#0e1116; color:#e6e6e6; border:1px solid #2b3138; border-radius:8px; padding:10px 12px; outline:none; }
  .cfg-small{ font-size:12px; opacity:.8; }

  /* Simple switch */
  .switch{ position:relative; display:inline-block; width:44px; height:24px; }
  .switch input{ opacity:0; width:0; height:0; }
  .slider{
    position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0;
    background:#2b3138; transition:.2s; border-radius:24px;
  }
  .slider:before{
    position:absolute; content:""; height:18px; width:18px; left:3px; top:3px;
    background:white; transition:.2s; border-radius:50%;
  }
  input:checked + .slider{ background:#238636; }
  input:checked + .slider:before{ transform:translateX(20px); }
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
          <button class="btn stop" onclick="stop()">STOP</button>
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
  </div>

  <!-- ===== Right-side vertical rail (menu) ===== -->
  <div id="right-rail" aria-label="Quick menu">
    <!-- Power toggle (top) -->
    <button id="power-toggle" class="fab" aria-label="Power" title="Power">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
           xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M12 3v6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        <path d="M6.8 7.8a7 7 0 1 0 10.4 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      </svg>
    </button>

    <!-- Shell toggle -->
    <button id="shell-toggle" class="fab" aria-label="Toggle shell" title="Command Shell">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none"
           xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" stroke-width="1.6" />
        <path d="M7 9l3 3-3 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
        <path d="M12.5 15H17" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
      </svg>
    </button>

    <!-- Config toggle -->
    <button id="config-toggle" class="fab" aria-label="Open settings" title="Settings">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
           xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
        <path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" stroke="currentColor" stroke-width="1.6" />
        <path d="M19 12a7 7 0 0 0-.09-1.1l1.98-1.54-2-3.46-2.35.95A7.02 7.02 0 0 0 14.2 5L14 3h-4l-.2 2a7.02 7.02 0 0 0-2.34.85l-2.36-.95-2 3.46 1.98 1.54A7 7 0 0 0 5 12c0 .37.03.73.09 1.1l-1.98 1.54 2 3.46 2.35-.95c.72.42 1.51.72 2.34.85l.2 2h4l.2-2c.83-.13 1.62-.43 2.34-.85l2.35.95 2-3.46-1.98-1.54c.06-.36.09-.73.09-1.1Z"
              stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
      </svg>
    </button>
  </div>

  <!-- Power popover -->
  <div id="power-pop" role="dialog" aria-modal="false" aria-label="Power actions">
    <button data-action="reboot">Restart</button>
    <button data-action="shutdown">Shut down</button>
  </div>

  <!-- ===== Shell Drawer ===== -->
  <div id="shell-drawer" class="drawer" aria-hidden="true">
    <div class="shell-head">
      <strong style="font-size:14px; letter-spacing:.3px;">Command Shell</strong>
      <div class="shell-actions">
        <button id="shell-clear" class="shell-btn" title="Clear output">Clear</button>
      </div>
    </div>

    <div class="shell-row">
      <input id="shell-input" type="text" class="shell-inp" placeholder="Enter command…" />
      <input id="shell-timeout" type="number" min="1" max="300" value="15"
             class="shell-inp" style="width:92px" title="Timeout (s)" />
      <button id="shell-run" class="shell-run">Run</button>
    </div>

    <pre id="shell-output" class="shell-out"></pre>
    <div id="shell-status" class="shell-status"></div>
  </div>

  <!-- ===== Config Drawer ===== -->
  <div id="config-drawer" class="drawer" aria-hidden="true">
    <div class="cfg-head">
      <strong style="font-size:14px; letter-spacing:.3px;">Configurations</strong>
      <div class="cfg-actions">
        <span class="cfg-small" id="cfg-mode-note"></span>
      </div>
    </div>

    <div class="cfg-row">
      <div class="cfg-label">Output path</div>
      <div class="cfg-flex">
        <input id="cfg-save-dir" type="text" class="cfg-inp" placeholder="/path/to/save" />
        <button id="cfg-save-dir-reset" class="cfg-btn" title="Restore default">Default</button>
      </div>
      <div class="cfg-small">Changes apply automatically.</div>
    </div>

    <div class="cfg-row">
      <div class="cfg-label">LED</div>
      <label class="cfg-flex cfg-small" style="gap:12px;">
        <span>Enable LED</span>
        <label class="switch">
          <input id="cfg-led" type="checkbox" />
          <span class="slider"></span>
        </label>
        <span id="cfg-led-note" class="cfg-small"></span>
      </label>
    </div>
  </div>

<script>
// ====== CONFIG ======
const POLL_EVERY_MS = 2000;
let   WINDOW_SEC    = 30;
const WINDOW_MS     = () => WINDOW_SEC * 1000;
const MAX_POINTS    = 5000;

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

// ====== SPARKLINE ======
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

// ====== Shell drawer logic (toggle + cls clear) ======
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

  function appendOut(kind, text) {
    const prefix = kind === 'stdout' ? '' : '[stderr] ';
    output.textContent += (prefix + (text || '')).replace(/\\r\\n/g, '\\n') + '\\n';
    output.scrollTop = output.scrollHeight;
  }

  async function runCommand() {
    const cmd = (input.value || '').trim();
    const timeout = Math.max(1, Math.min(parseInt(tout.value || '15', 10), 300));
    if (!cmd) return;

    // Intercept 'cls' to clear web shell immediately
    if (cmd.toLowerCase() === 'cls') {
      output.textContent = '';
      input.select();
      return;
    }

    runBtn.disabled = true;
    status.textContent = 'Running…';
    output.textContent += `$ ${cmd}\\n`;
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
        output.textContent += `[exit=${data.code ?? '—'} ok=${data.ok} elapsed=${data.elapsed_sec ?? '—'}s${data.timeout ? ' TIMEOUT' : ''}]\\n\\n`;
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

// ====== Config drawer logic (auto-apply path, LED toggle) ======
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

// ====== Power (popover + confirm) ======
(function () {
  const btn = document.getElementById('power-toggle');
  const pop = document.getElementById('power-pop');

  function togglePop() {
    pop.classList.toggle('open');
    btn.classList.toggle('active', pop.classList.contains('open'));
  }
  function closePop() {
    pop.classList.remove('open');
    btn.classList.remove('active');
  }

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

# Optional: run with `python main.py`
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
