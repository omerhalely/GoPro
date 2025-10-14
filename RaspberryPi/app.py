from flask import Flask, jsonify, request, render_template, send_from_directory, Response, stream_with_context
import threading, time, os, subprocess, platform, mimetypes
from utils import _res_to_str, _parse_res_str

# Try imports of capture image and video
try:
    from ImageCapture import image_capture
except Exception:
    image_capture = None
try:
    from VideoCapture import video_capture
except Exception:
    video_capture = None


app = Flask(__name__, static_folder="static", template_folder="templates")

# ── Settings ──────────────────────────────────────────────────────────────────
DEFAULT_SAVE_DIR = "./outputs"   # fixed default output directory
if not os.path.exists(DEFAULT_SAVE_DIR):
    os.mkdir(DEFAULT_SAVE_DIR)

# ── DEV toggle ────────────────────────────────────────────────────────────────
DEVELOPMENT_MODE = False  # ← set False on the Raspberry Pi for real actions

# ── Shell console settings ────────────────────────────────────────────────────
SHELL_ENABLED = True               # ⚠️ Anyone with page access can run commands
SHELL_TIMEOUT_DEFAULT = 15         # seconds
SHELL_MAX_CHARS = 100_000          # cap combined stdout/stderr size

# ── Mutable runtime config (server-side) ──────────────────────────────────────
CURRENT_SAVE_DIR = DEFAULT_SAVE_DIR
LED_ON = False   # tracked state; no-op in DEVELOPMENT_MODE

# === Capture defaults ===
IMAGE_RES_DEFAULT = (640, 480)
VIDEO_RES_DEFAULT = (640, 480)
VIDEO_FPS_DEFAULT = 25

# === Current (mutable) settings ===
CURRENT_IMAGE_RES = list(IMAGE_RES_DEFAULT)  # [w, h]
CURRENT_VIDEO_RES = list(VIDEO_RES_DEFAULT)  # [w, h]
CURRENT_VIDEO_FPS = VIDEO_FPS_DEFAULT

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
    # snapshot the directory at start (avoids races if CURRENT_SAVE_DIR changes mid-run)
    save_dir = os.path.abspath(CURRENT_SAVE_DIR)

    try:
        # ensure output dir exists
        if not os.path.exists(save_dir):
            try:
                os.makedirs(save_dir, exist_ok=True)
                print(f"[capture] Created output directory: {save_dir}")
            except Exception as e:
                print(f"[capture][error] Could not create output directory '{save_dir}': {e}")
                return  # abort the thread gracefully

        print(f"[capture] Saving video to: {save_dir}")

        if DEVELOPMENT_MODE:
            while not _stop_evt.is_set():
                time.sleep(0.25)
        else:
            video_capture(_stop_evt, output_dir=save_dir)  # plug in on the Pi

    finally:
        # mark not running even on error or stop
        with _state_lock:
            global _is_running
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
        # TODO: implement GPIO control (RPi.GPIO / gpiozero)
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
@app.route("/start", methods=["GET"])
def start_capture():
    global _capture_thread, _is_running, _last_start_ts
    with _state_lock:
        if _is_running:
            return jsonify({"error": "Capture already running"}), 409
        _stop_evt.clear()
        _is_running = True
        _last_start_ts = int(time.time())
        _capture_thread = threading.Thread(target=_run_capture_thread, daemon=True)
        _capture_thread.start()
    return jsonify({"status": "started", "started_ts": _last_start_ts, "save_dir": CURRENT_SAVE_DIR})

@app.route("/stop", methods=["GET"])
def stop_capture():
    _stop_evt.set()
    return jsonify({"status": "stop signaled"})

@app.route("/status", methods=["GET"])
def status():
    with _state_lock:
        return jsonify({"running": _is_running, "started_ts": _last_start_ts, "save_dir": CURRENT_SAVE_DIR})

@app.route("/capture_image", methods=["POST"])
def capture_image_endpoint():
    """
    Captures a still image and saves it under CURRENT_SAVE_DIR.
    Returns: {"ok": bool, "path": "<full path>", "dev": bool}
    """
    save_dir = os.path.abspath(CURRENT_SAVE_DIR)

    # ensure directory exists (same pattern as video)
    if not os.path.exists(save_dir):
        try:
            os.makedirs(save_dir, exist_ok=True)
            print(f"[still] Created output directory: {save_dir}")
        except Exception as e:
            return jsonify({"ok": False, "error": f"Cannot create directory: {e}"}), 500

    # call real capture if available
    try:
        if image_capture is not None and not DEVELOPMENT_MODE:
            path = image_capture(save_dir)  # <-- your real function must return full path
            if not path:
                return jsonify({"ok": False, "error": "capture_image() returned no path"}), 500
            return jsonify({"ok": True, "path": path, "dev": False})
        else:
            # DEV fallback: create a dummy jpg file
            ts = int(time.time())
            fname = f"snapshot_{ts}.jpg"
            fpath = os.path.join(save_dir, fname)
            return jsonify({"ok": True, "path": fpath, "dev": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── Live preview ──────────────────────────────────────────────────────────
@app.route("/preview.mjpg", methods=["GET"])
def preview_mjpg():
    """
    Streams multipart/x-mixed-replace MJPEG. Works on the Pi with cv2.
    In DEV mode, return 503 so the frontend shows a canvas placeholder.
    """
    if DEVELOPMENT_MODE:
        return jsonify({"ok": False, "error": "Preview not available in DEV"}), 503

    try:
        import cv2
    except Exception as e:
        return jsonify({"ok": False, "error": f"OpenCV not available: {e}"}), 503

    def gen():
        cap = None
        try:
            cap = cv2.VideoCapture(0)
            # Try to respect current video resolution if set
            try:
                vw, vh = CURRENT_VIDEO_RES  # ensure these exist in your config
                if vw and vh:
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  vw)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, vh)
            except Exception:
                pass

            if not cap.isOpened():
                raise RuntimeError("Camera not available")

            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                # Optionally resize to CURRENT_VIDEO_RES
                try:
                    vw, vh = CURRENT_VIDEO_RES
                    if vw and vh:
                        import cv2 as _cv
                        frame = _cv.resize(frame, (int(vw), int(vh)))
                except Exception:
                    pass

                ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok:
                    continue
                jpg = buffer.tobytes()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" +
                    jpg + b"\r\n"
                )
        finally:
            if cap is not None:
                try: cap.release()
                except Exception: pass

    return Response(stream_with_context(gen()),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/files", methods=["GET"])
def list_files():
    """
    List entries under CURRENT_SAVE_DIR (dirs/files).
    Query param:
      - path="" (relative path inside CURRENT_SAVE_DIR)
    Returns:
      { base, path, entries:[{name,type, size, mtime, path}] }
    """
    try:
        rel = (request.args.get("path") or "").strip().lstrip("/\\")
        base = os.path.abspath(CURRENT_SAVE_DIR)
        target = os.path.abspath(os.path.join(base, rel))

        # security: must stay under base
        if not target.startswith(base):
            return jsonify({"ok": False, "error": "Invalid path"}), 400

        if not os.path.exists(target):
            return jsonify({"ok": False, "error": "Not found"}), 404

        entries = []
        names = []
        try:
            names = os.listdir(target)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Cannot list directory: {e}"}), 500

        # Sort: directories first, then files (A–Z)
        names.sort(key=lambda n: (not os.path.isdir(os.path.join(target, n)), n.lower()))

        for name in names[:2000]:  # soft cap
            full = os.path.join(target, name)
            try:
                st = os.stat(full)
                entries.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": st.st_size if os.path.isfile(full) else None,
                    "mtime": st.st_mtime,
                    "path": os.path.relpath(full, base).replace("\\", "/")
                })
            except Exception:
                continue

        rel_out = "" if target == base else os.path.relpath(target, base).replace("\\", "/")
        return jsonify({
            "ok": True,
            "base": base,
            "path": rel_out,
            "entries": entries
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/media", methods=["GET"])
def serve_media():
    """
    GET /media?path=relative/path/from/CURRENT_SAVE_DIR
    - Validates path stays inside CURRENT_SAVE_DIR
    - Sets correct mimetype
    - Supports Range requests for video/audio
    """
    rel = (request.args.get("path") or "").strip().lstrip("/\\")
    base = os.path.abspath(CURRENT_SAVE_DIR)
    target = os.path.abspath(os.path.join(base, rel))

    if not target.startswith(base):
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    if not os.path.exists(target) or not os.path.isfile(target):
        return jsonify({"ok": False, "error": "Not found"}), 404

    file_size = os.path.getsize(target)
    mime, _ = mimetypes.guess_type(target)
    if not mime:
        mime = "application/octet-stream"

    # Handle Range requests (bytes=START-END)
    range_header = request.headers.get("Range", None)
    if range_header:
        # Example: "bytes=0-" or "bytes=1000-2000"
        try:
            units, rng = range_header.split("=")
            if units.strip() != "bytes":
                raise ValueError
            start_end = rng.split("-")
            start = int(start_end[0]) if start_end[0] else 0
            end = int(start_end[1]) if len(start_end) > 1 and start_end[1] else file_size - 1
            start = max(0, start)
            end = min(end, file_size - 1)
            if start > end:
                start = 0
                end = file_size - 1
        except Exception:
            start, end = 0, file_size - 1

        length = end - start + 1

        def generate():
            with open(target, "rb") as f:
                f.seek(start)
                chunk_size = 8192
                remaining = length
                while remaining > 0:
                    data = f.read(min(chunk_size, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        rv = Response(generate(), status=206, mimetype=mime,
                      direct_passthrough=True)
        rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
        rv.headers.add("Accept-Ranges", "bytes")
        rv.headers.add("Content-Length", str(length))
        return rv

    # No range: return full file
    def generate_full():
        with open(target, "rb") as f:
            while True:
                data = f.read(8192)
                if not data:
                    break
                yield data

    rv = Response(generate_full(), mimetype=mime, direct_passthrough=True)
    rv.headers.add("Content-Length", str(file_size))
    rv.headers.add("Accept-Ranges", "bytes")
    return rv

# ── Config endpoints ──────────────────────────────────────────────────────────
@app.route("/config", methods=["GET"])
def get_config():
    return jsonify({
        "development_mode": DEVELOPMENT_MODE,
        "save_dir_default": DEFAULT_SAVE_DIR,
        "save_dir_current": CURRENT_SAVE_DIR,

        # NEW:
        "image_res_default": _res_to_str(IMAGE_RES_DEFAULT),
        "image_res_current": _res_to_str(CURRENT_IMAGE_RES),
        "video_res_default": _res_to_str(VIDEO_RES_DEFAULT),
        "video_res_current": _res_to_str(CURRENT_VIDEO_RES),
        "video_fps_default": VIDEO_FPS_DEFAULT,
        "video_fps_current": CURRENT_VIDEO_FPS,

        # keep whatever else you already return (e.g., led_on)
        "led_on": False if DEVELOPMENT_MODE else False,  # example / placeholder
    })

@app.route("/config", methods=["POST"])
def post_config():
    global CURRENT_SAVE_DIR, CURRENT_IMAGE_RES, CURRENT_VIDEO_RES, CURRENT_VIDEO_FPS
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    # Save dir (already supported in your app)
    save_dir = body.get("save_dir")
    if isinstance(save_dir, str) and save_dir.strip():
        CURRENT_SAVE_DIR = save_dir.strip()

    # LED (no-op in DEV – keep your existing handling if you have it)
    # led_on = body.get("led_on")  # ignore/do nothing in DEV

    # NEW: image resolution
    img_res = body.get("image_res")
    if isinstance(img_res, str):
        parsed = _parse_res_str(img_res)
        if parsed:
            CURRENT_IMAGE_RES = list(parsed)

    # NEW: video resolution
    vid_res = body.get("video_res")
    if isinstance(vid_res, str):
        parsed = _parse_res_str(vid_res)
        if parsed:
            CURRENT_VIDEO_RES = list(parsed)

    # NEW: video fps
    fps = body.get("video_fps")
    try:
        if fps is not None:
            fps = int(fps)
            if 1 <= fps <= 120:  # reasonable guard
                CURRENT_VIDEO_FPS = fps
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "save_dir_current": CURRENT_SAVE_DIR,
        "image_res_current": _res_to_str(CURRENT_IMAGE_RES),
        "video_res_current": _res_to_str(CURRENT_VIDEO_RES),
        "video_fps_current": CURRENT_VIDEO_FPS,
    })

# ── Power endpoint (restart/shutdown) ─────────────────────────────────────────
@app.route("/power", methods=["POST"])
def power_action():
    """
    Body: {"action": "reboot" | "shutdown"}
    DEV mode: simulate only.
    PROD: run real commands (requires sudo privileges).
    """
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}
    action = (body.get("action") or "").lower()
    if action not in ("reboot", "shutdown"):
        return jsonify({"ok": False, "error": "Invalid action (use 'reboot' or 'shutdown')"}), 400

    if DEVELOPMENT_MODE:
        return jsonify({"ok": True, "dev": True, "action": action, "message": f"Simulated {action} in DEV mode."})

    try:
        if action == "reboot":
            cmd = ["sudo", "reboot"]
        else:
            cmd = ["sudo", "shutdown", "-h", "now"]
        subprocess.Popen(cmd)  # do not wait
        return jsonify({"ok": True, "dev": False, "action": action, "message": f"{action} command sent."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── API endpoint: live metrics ────────────────────────────────────────────────
@app.route("/metrics", methods=["GET"])
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
    return jsonify({
        "ts": ts,
        "sensors": {"current_a": rnd(amps, 3), "voltage_v": rnd(volts, 3)},
        "cpu": {"temp_c": rnd(cpu_temp, 1), "util_pct": rnd(cpu_util, 1), "freq_mhz": rnd(cpu_mhz, 0)},
        "gpu": {"temp_c": rnd(gpu_temp, 1)},
        "ram": {"used_pct": rnd(ram_used, 1)},
        "disk": {"free_pct": rnd(disk_free, 1), "path": CURRENT_SAVE_DIR}
    })

# ── API endpoint: shell command execution ─────────────────────────────────────
@app.route("/shell", methods=["POST"])
def run_shell():
    if not SHELL_ENABLED:
        return jsonify({"error": "Shell disabled on server"}), 403

    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    cmd = (body.get("cmd") or "").strip()
    if not cmd:
        return jsonify({"error": "Missing 'cmd'"}), 400

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
                exec_cmd, capture_output=True, text=True, timeout=timeout,
                encoding="oem", errors="replace"
            )
        else:
            exec_cmd = ["bash", "-lc", cmd]
            res = subprocess.run(
                exec_cmd, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace"
            )
        elapsed = time.time() - start
    except subprocess.TimeoutExpired as e:
        return jsonify({
            "ok": False, "timeout": True, "code": None,
            "elapsed_sec": round(time.time() - start, 3),
            "stdout": (e.stdout or "")[:SHELL_MAX_CHARS],
            "stderr": (e.stderr or "")[:SHELL_MAX_CHARS],
            "ran": exec_cmd if 'exec_cmd' in locals() else cmd,
        }), 504

    stdout = (res.stdout or "")[:SHELL_MAX_CHARS]
    stderr = (res.stderr or "")[:SHELL_MAX_CHARS]

    return jsonify({
        "ok": res.returncode == 0,
        "code": res.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout": stdout,
        "stderr": stderr,
        "ran": exec_cmd,
    })

# ── Web UI ────────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# Static files (served by Flask automatically via app.static_folder)
@app.route("/static/<path:path>", methods=["GET"])
def send_static(path):
    return send_from_directory(app.static_folder, path)

# Run: python app.py
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
