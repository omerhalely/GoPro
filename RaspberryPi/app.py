"""
PiCam Controller — Flask server

Features:
- Start/stop video capture in a background thread (Picamera2 + H.264 encoder)
- Still image capture
- Live MJPEG preview
- File browser API (list/serve) + safe delete (soft delete to .trash/) + forced download
- System metrics endpoints (CPU/GPU temp, CPU util/clock, RAM, disk free)
- Simple shell execution endpoint (optional, gated by flag)
- Config endpoints (save dir, resolutions, FPS)
- Optional power actions (reboot/shutdown) on real Pi

Notes:
- In DEV mode, camera/power/metrics are stubbed for safety.
- Video/still capture are delegated to ImageCapture.py & VideoCapture.py if present.
"""

from __future__ import annotations

import os
import cv2
import time
import uuid
import shutil
import platform
import threading
import subprocess
import mimetypes
from typing import Optional, Tuple

from flask import (
    Flask, jsonify, request, render_template, send_from_directory,
    Response
)

# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------

app = Flask(__name__, static_folder="static", template_folder="templates")

# ===== Settings =====
DEFAULT_SAVE_DIR = "./outputs"  # Default output directory for media
os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)

# Toggle for safe development without touching hardware
DEVELOPMENT_MODE: bool = True  # Set to False on the Raspberry Pi

# Shell console settings (CAUTION: exposes command execution on your LAN)
SHELL_ENABLED: bool = True
SHELL_TIMEOUT_DEFAULT: int = 15  # seconds
SHELL_MAX_CHARS: int = 100_000

# ===== Mutable runtime config (server-side) =====
CURRENT_SAVE_DIR = DEFAULT_SAVE_DIR
LED_ON = False  # placeholder (GPIO not implemented)

# Capture defaults
IMAGE_RES_DEFAULT: Tuple[int, int] = (640, 480)
VIDEO_RES_DEFAULT: Tuple[int, int] = (640, 480)
VIDEO_FPS_DEFAULT: int = 25

# Current (mutable) settings exposed via /config
CURRENT_IMAGE_RES = list(IMAGE_RES_DEFAULT)  # [w, h]
CURRENT_VIDEO_RES = list(VIDEO_RES_DEFAULT)  # [w, h]
CURRENT_VIDEO_FPS = VIDEO_FPS_DEFAULT

# -----------------------------------------------------------------------------
# Optional imports (Picamera2 + user capture modules)
# -----------------------------------------------------------------------------

try:
    from ImageCapture import image_capture  # def image_capture(save_dir) -> str
except Exception as e:
    if not DEVELOPMENT_MODE:
        print("[ImageCapture import error]", e)
    image_capture = None

try:
    from VideoCapture import video_capture  # def video_capture(output_dir,...)
except Exception as e:
    if not DEVELOPMENT_MODE:
        print("[VideoCapture import error]", e)
    video_capture = None

try:
    from picamera2 import Picamera2
except Exception as e:
    if not DEVELOPMENT_MODE:
        print("[Picamera2 import error]", e)
    Picamera2 = None  # type: ignore


def _randf(lo: float, hi: float) -> float:
    """Return a random float in [lo, hi] without importing random."""
    r = int.from_bytes(os.urandom(8), "big") / (1 << 64)
    return lo + (hi - lo) * r


# -----------------------------------------------------------------------------
# Global state for recording thread
# -----------------------------------------------------------------------------

_state_lock = threading.Lock()
_is_running: bool = False
_stop_evt = threading.Event()
_capture_thread: Optional[threading.Thread] = None
_last_start_ts: Optional[int] = None

# CPU utilization bookkeeping (when not in DEV)
_prev_total = None
_prev_idle = None

# Lazily-created Picamera2 instance for preview only
_picam2 = None
_picam_lock = threading.Lock()
_preview_fps = 25

# -----------------------------------------------------------------------------
# Helpers (parsing/formatting)
# -----------------------------------------------------------------------------

def _res_to_str(res: Tuple[int, int] | list[int]) -> str:
    """Convert (w,h) to 'WxH' string."""
    try:
        w, h = int(res[0]), int(res[1])
        return f"{w}x{h}"
    except Exception:
        return "—"


def _parse_res_str(s: str) -> Optional[Tuple[int, int]]:
    """Parse 'WxH' into (w,h) ints. Returns None on failure."""
    try:
        parts = s.lower().split("x")
        if len(parts) != 2:
            return None
        w, h = int(parts[0]), int(parts[1])
        if w <= 0 or h <= 0:
            return None
        return (w, h)
    except Exception:
        return None


def _safe_under_base(base: str, rel: str) -> str:
    """
    Resolve a user-supplied relative path under base, ensuring no directory traversal.

    Raises:
        ValueError: if resolved path escapes base.
    """
    rel = (rel or "").strip().lstrip("/\\")
    target = os.path.abspath(os.path.join(base, rel))
    if not target.startswith(os.path.abspath(base)):
        raise ValueError("Invalid path")
    return target


# -----------------------------------------------------------------------------
# Capture thread runner
# -----------------------------------------------------------------------------

def _run_capture_thread() -> None:
    """
    Background thread entry point that starts a video recording until _stop_evt is set.

    Behavior:
      - Ensures output directory exists
      - Chooses bitrate heuristically based on CURRENT_VIDEO_RES
      - Delegates to VideoCapture.video_capture(...) when not in DEV
      - On exit, marks recording state as stopped
    """
    global _picam2
    save_dir = os.path.abspath(CURRENT_SAVE_DIR)

    try:
        # Ensure output dir exists (fail gracefully)
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            print(f"[capture][error] Could not create output directory '{save_dir}': {e}")
            return

        print(f"[capture] Saving video to: {save_dir}")

        if DEVELOPMENT_MODE:
            # Simulate recording
            while not _stop_evt.is_set():
                time.sleep(0.25)
        else:
            # Ensure no preview instance conflicts with recording
            if _picam2 is not None:
                try:
                    _picam2.stop()
                except Exception:
                    pass
                try:
                    _picam2.close()
                except Exception:
                    pass
                _picam2 = None

            # Simple bitrate map
            w, h = int(CURRENT_VIDEO_RES[0]), int(CURRENT_VIDEO_RES[1])
            if (w, h) == (320, 240):
                bitrate = 1_000_000
            elif (w, h) == (1280, 960):
                bitrate = 10_000_000
            else:
                bitrate = 3_000_000  # default for 640x480

            # Call user module (hardware encode to MP4 recommended)
            if video_capture is None:
                print("[capture][error] VideoCapture.video_capture not available")
                return

            video_capture(
                output_dir=save_dir,
                stop_evt=_stop_evt,
                width=w,
                height=h,
                fps=int(CURRENT_VIDEO_FPS),
                bitrate=int(bitrate),
            )
    finally:
        # Mark as not running even on error or stop
        with _state_lock:
            global _is_running
            _is_running = False
        _stop_evt.clear()


# -----------------------------------------------------------------------------
# System metrics (DEV stubs + real on Pi)
# -----------------------------------------------------------------------------

def _read_cpu_temp_c() -> Optional[float]:
    """Return CPU temperature in °C, or None if unavailable (DEV may simulate)."""
    if DEVELOPMENT_MODE:
        return round(_randf(38.0, 72.0), 1)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return float(f.read().strip()) / 1000.0
    except Exception:
        return None


def _read_gpu_temp_c() -> Optional[float]:
    """Return GPU temperature in °C via vcgencmd, or None if unavailable."""
    if DEVELOPMENT_MODE:
        return round(_randf(40.0, 70.0), 1)
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"], text=True, timeout=1)
        if "temp=" in out:
            return float(out.split("temp=")[1].split("'")[0])
    except Exception:
        pass
    return None


def _read_cpu_util_percent() -> Optional[float]:
    """
    Return CPU utilization percent based on /proc/stat deltas, or None on first call.
    DEV mode returns simulated values.
    """
    if DEVELOPMENT_MODE:
        base = _randf(8.0, 35.0)
        spike = _randf(0, 1)
        return round(base + (50.0 if spike > 0.95 else 0.0), 1)
    global _prev_total, _prev_idle
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return None
        parts = [float(x) for x in line.split()[1:11]]
        user, nice, system, idle, iowait, irq, softirq, steal, *_ = (parts + [0] * 10)[:8]
        idle_all = idle + iowait
        non_idle = user + nice + system + irq + softirq + steal
        total = idle_all + non_idle
        if _prev_total is None:
            _prev_total, _prev_idle = total, idle_all
            return None
        totald = total - _prev_total
        idled = idle_all - _prev_idle
        _prev_total, _prev_idle = total, idle_all
        if totald <= 0:
            return None
        return max(0.0, min(100.0, (totald - idled) * 100.0 / totald))
    except Exception:
        return None


def _read_ram_percent_used() -> Optional[float]:
    """Return RAM used percent by parsing /proc/meminfo, or None if unavailable."""
    if DEVELOPMENT_MODE:
        return round(_randf(20.0, 85.0), 1)
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


def _read_disk_free_percent(path: str) -> Optional[float]:
    """Return free disk percent for filesystem containing 'path', or None."""
    if DEVELOPMENT_MODE:
        return round(_randf(35.0, 95.0), 1)
    try:
        st = os.statvfs(path)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total <= 0:
            return None
        return free * 100.0 / total
    except Exception:
        return None


def _read_cpu_freq_mhz() -> Optional[float]:
    """Return current CPU frequency in MHz, or None if unavailable."""
    if DEVELOPMENT_MODE:
        return round(_randf(600.0, 1500.0), 0)
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


def _set_led(on: bool) -> None:
    """Set LED state (placeholder; implement with GPIO if desired)."""
    global LED_ON
    LED_ON = bool(on)
    if DEVELOPMENT_MODE:
        return
    try:
        # TODO: implement actual GPIO control
        pass
    except Exception:
        pass


def _read_voltage_current() -> Tuple[Optional[float], Optional[float]]:
    """Return (current_A, voltage_V) from a sensor if present; DEV simulates."""
    if DEVELOPMENT_MODE:
        volts = round(_randf(4.80, 5.20), 3)
        amps = round(_randf(0.10, 2.50), 3)
        return amps, volts
    try:
        # TODO: read from e.g., INA219/INA260 if wired
        return None, None
    except Exception:
        return None, None


# -----------------------------------------------------------------------------
# Preview camera (MJPEG)
# -----------------------------------------------------------------------------

def _ensure_picam2():
    """
    (Re)create a lightweight Picamera2 instance configured for preview streaming.

    Returns:
        A started Picamera2 instance using BGR888 for OpenCV-friendly JPEG encoding.
    """
    global _picam2
    with _picam_lock:
        # Always reset to avoid conflicts with recording instance
        if _picam2 is not None:
            try:
                _picam2.stop()
            except Exception:
                pass
            try:
                _picam2.close()
            except Exception:
                pass
            _picam2 = None

        if Picamera2 is None:
            raise RuntimeError("Picamera2 is not available")

        picam2 = Picamera2()
        width = int(CURRENT_VIDEO_RES[0])
        height = int(CURRENT_VIDEO_RES[1])

        # Use BGR888 so OpenCV jpeg encoding doesn't swap colors
        config = picam2.create_preview_configuration(
            main={"size": (width, height), "format": "BGR888"},
            controls={
                "FrameRate": int(CURRENT_VIDEO_FPS),
                "AeEnable": True,
                "Sharpness": 1.0,
                "Contrast": 1.05,
                "Saturation": 1.05,
            }
        )
        picam2.configure(config)
        picam2.start()
        _picam2 = picam2
        return _picam2


# -----------------------------------------------------------------------------
# API: Capture control
# -----------------------------------------------------------------------------

@app.route("/start", methods=["GET"])
def start_capture():
    """
    Start video capture in a background thread.

    Returns:
        JSON: {"status": "started", "started_ts": <epoch>, "save_dir": <dir>}
              or an error if already running.
    """
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
    """
    Signal the background capture thread to stop.

    Returns:
        JSON: {"status": "stop signaled"}
    """
    _stop_evt.set()
    return jsonify({"status": "stop signaled"})


@app.route("/status", methods=["GET"])
def status():
    """
    Return current capture state and configuration.

    Returns:
        JSON: {"running": bool, "started_ts": int|None, "save_dir": str}
    """
    with _state_lock:
        return jsonify({"running": _is_running, "started_ts": _last_start_ts, "save_dir": CURRENT_SAVE_DIR})


@app.route("/capture_image", methods=["POST"])
def capture_image_endpoint():
    """
    Capture a still image and save it under CURRENT_SAVE_DIR.

    Returns:
        JSON:
          - {"ok": True, "path": "<full path>", "dev": False} on success (hardware)
          - {"ok": True, "path": "<full path>", "dev": True} in DEV fallback
          - {"ok": False, "error": "..."} on failure
    """
    save_dir = os.path.abspath(CURRENT_SAVE_DIR)

    # Ensure directory exists
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception as e:
        return jsonify({"ok": False, "error": f"Cannot create directory: {e}"}), 500

    # Call real capture if available
    try:
        if image_capture is not None and not DEVELOPMENT_MODE:
            path = image_capture(save_dir)  # your function should return full path
            if not path:
                return jsonify({"ok": False, "error": "capture_image() returned no path"}), 500
            return jsonify({"ok": True, "path": path, "dev": False})
        else:
            # DEV fallback: return a predictable filename (not actually created here)
            ts = int(time.time())
            fname = f"snapshot_{ts}.jpg"
            fpath = os.path.join(save_dir, fname)
            return jsonify({"ok": True, "path": fpath, "dev": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# -----------------------------------------------------------------------------
# API: Live MJPEG preview
# -----------------------------------------------------------------------------

@app.route("/preview.mjpg", methods=["GET"])
def preview_mjpg():
    """
    Stream a MJPEG preview from the camera using multipart/x-mixed-replace.

    DEV mode:
        Returns 503 since no real camera is used.
    PROD:
        Uses a dedicated Picamera2 instance configured for BGR888 and encodes
        each frame as JPEG (quality=80).
    """
    if DEVELOPMENT_MODE:
        return jsonify({"ok": False, "error": "Preview disabled in DEV"}), 503

    try:
        cam = _ensure_picam2()
    except Exception as e:
        print("[preview] init failed:", e)
        return jsonify({"ok": False, "error": f"camera init failed: {e}"}), 503

    def gen():
        delay = 1.0 / max(1, _preview_fps)
        while True:
            try:
                bgr = cam.capture_array()  # shape (H,W,3), dtype=uint8
                ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok:
                    time.sleep(delay)
                    continue
                jpg = buf.tobytes()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" +
                    jpg + b"\r\n"
                )
            except GeneratorExit:
                break
            except Exception:
                time.sleep(delay)
                continue

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")


# -----------------------------------------------------------------------------
# API: Filesystem listing / serving / delete
# -----------------------------------------------------------------------------

@app.route("/files", methods=["GET"])
def list_files():
    """
    List files and directories under CURRENT_SAVE_DIR.

    Query params:
        path: str  (relative path inside CURRENT_SAVE_DIR; default root)

    Returns:
        JSON: { ok, base, path, entries:[{name,type,size,mtime,path}] }
              path is relative to base; entries sorted: directories first.
    """
    try:
        rel = (request.args.get("path") or "").strip().lstrip("/\\")
        base = os.path.abspath(CURRENT_SAVE_DIR)
        target = os.path.abspath(os.path.join(base, rel))

        # Security: must stay under base
        if not target.startswith(base):
            return jsonify({"ok": False, "error": "Invalid path"}), 400

        if not os.path.exists(target):
            return jsonify({"ok": False, "error": "Not found"}), 404

        entries = []
        try:
            names = os.listdir(target)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Cannot list directory: {e}"}), 500

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
    Serve files under CURRENT_SAVE_DIR with Range support (video seeking).

    Query params:
        path: str      (relative path inside CURRENT_SAVE_DIR)
        download: bool (if '1'/'true' => force Content-Disposition: attachment)

    Returns:
        Streaming Response with correct mimetype and range handling.
    """
    rel = (request.args.get("path") or "").strip().lstrip("/\\")
    base = os.path.abspath(CURRENT_SAVE_DIR)
    target = os.path.abspath(os.path.join(base, rel))
    force_download = (request.args.get("download") in ("1", "true", "yes"))

    if not target.startswith(base):
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    if not os.path.exists(target) or not os.path.isfile(target):
        return jsonify({"ok": False, "error": "Not found"}), 404

    file_size = os.path.getsize(target)
    mime, _ = mimetypes.guess_type(target)
    if not mime:
        mime = "application/octet-stream"

    def add_download_headers(rv: Response) -> Response:
        """Optionally force 'Save as' behavior."""
        if force_download:
            rv.headers.add("Content-Disposition", f'attachment; filename="{os.path.basename(target)}"')
        return rv

    range_header = request.headers.get("Range", None)
    if range_header:
        # bytes=START-END
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
                start, end = 0, file_size - 1
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

        rv = Response(generate(), status=206, mimetype=mime, direct_passthrough=True)
        rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
        rv.headers.add("Accept-Ranges", "bytes")
        rv.headers.add("Content-Length", str(length))
        return add_download_headers(rv)

    # No range: full file
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
    return add_download_headers(rv)


@app.route("/delete", methods=["POST"])
def delete_entry():
    """
    Delete file/folder under CURRENT_SAVE_DIR.

    Body (JSON):
        {
          "path": "relative/path/from/CURRENT_SAVE_DIR",
          "permanent": false  # default False => soft delete (move to .trash/)
        }

    Behavior:
        - Soft delete: move target into <CURRENT_SAVE_DIR>/.trash/<name_uuid>
        - Permanent:   remove file or recursively remove directory
        - Refuses to delete the root directory itself

    Returns:
        JSON: { ok, action: "moved_to_trash"|"deleted", path, disk_free_pct }
    """
    base = os.path.abspath(CURRENT_SAVE_DIR)
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    rel = (body.get("path") or "").strip()
    permanent = bool(body.get("permanent", False))

    if not rel:
        return jsonify({"ok": False, "error": "Missing 'path'"}), 400

    try:
        target = _safe_under_base(base, rel)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if not os.path.exists(target):
        return jsonify({"ok": False, "error": "Not found"}), 404

    # Extra guard: do not allow deleting the base itself
    if os.path.abspath(target) == base:
        return jsonify({"ok": False, "error": "Refusing to delete the root directory"}), 400

    try:
        if permanent:
            if os.path.isdir(target) and not os.path.islink(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
            action = "deleted"
        else:
            trash_dir = os.path.join(base, ".trash")
            os.makedirs(trash_dir, exist_ok=True)
            name = os.path.basename(target.rstrip(os.sep)) or "item"
            uid = uuid.uuid4().hex[:8]
            root, ext = os.path.splitext(name)
            trash_name = f"{root}_{uid}{ext}" if ext else f"{name}_{uid}"
            dest = os.path.join(trash_dir, trash_name)
            shutil.move(target, dest)
            action = "moved_to_trash"

        free_pct = _read_disk_free_percent(CURRENT_SAVE_DIR)
        return jsonify({
            "ok": True,
            "action": action,
            "path": rel,
            "disk_free_pct": None if free_pct is None else round(free_pct, 1)
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# -----------------------------------------------------------------------------
# API: Config
# -----------------------------------------------------------------------------

@app.route("/config", methods=["GET"])
def get_config():
    """
    Return current configuration and defaults for client UI.

    Returns:
        JSON with development_mode, directories, resolutions, FPS, LED.
    """
    return jsonify({
        "development_mode": DEVELOPMENT_MODE,
        "save_dir_default": DEFAULT_SAVE_DIR,
        "save_dir_current": CURRENT_SAVE_DIR,

        "image_res_default": _res_to_str(IMAGE_RES_DEFAULT),
        "image_res_current": _res_to_str(CURRENT_IMAGE_RES),
        "video_res_default": _res_to_str(VIDEO_RES_DEFAULT),
        "video_res_current": _res_to_str(CURRENT_VIDEO_RES),
        "video_fps_default": VIDEO_FPS_DEFAULT,
        "video_fps_current": CURRENT_VIDEO_FPS,

        "led_on": False if DEVELOPMENT_MODE else False,
    })


@app.route("/config", methods=["POST"])
def post_config():
    """
    Update mutable configuration from JSON body.

    Body (any optional):
        {
          "save_dir": "/path/to/save",
          "image_res": "WxH",
          "video_res": "WxH",
          "video_fps": int
        }

    Returns:
        JSON echoing the effective config after update.
    """
    global CURRENT_SAVE_DIR, CURRENT_IMAGE_RES, CURRENT_VIDEO_RES, CURRENT_VIDEO_FPS
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    # Save dir
    save_dir = body.get("save_dir")
    if isinstance(save_dir, str) and save_dir.strip():
        CURRENT_SAVE_DIR = save_dir.strip()

    # Image resolution
    img_res = body.get("image_res")
    if isinstance(img_res, str):
        parsed = _parse_res_str(img_res)
        if parsed:
            CURRENT_IMAGE_RES = list(parsed)

    # Video resolution
    vid_res = body.get("video_res")
    if isinstance(vid_res, str):
        parsed = _parse_res_str(vid_res)
        if parsed:
            CURRENT_VIDEO_RES = list(parsed)

    # Video FPS
    fps = body.get("video_fps")
    try:
        if fps is not None:
            fps = int(fps)
            if 1 <= fps <= 120:
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


# -----------------------------------------------------------------------------
# API: Power (reboot/shutdown)
# -----------------------------------------------------------------------------

@app.route("/power", methods=["POST"])
def power_action():
    """
    Perform a power action: reboot or shutdown (requires sudo on real Pi).

    Body:
        {"action": "reboot" | "shutdown"}

    DEV mode:
        Returns a simulated success without running any command.
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


# -----------------------------------------------------------------------------
# API: Metrics
# -----------------------------------------------------------------------------

@app.route("/metrics", methods=["GET"])
def metrics():
    """
    Return a snapshot of system metrics for the UI graphs.

    Returns:
        JSON with timestamps and numeric fields for CPU/GPU temp, CPU util/clock,
        RAM used percent, disk free percent, and optional sensor (A/V).
    """
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


# -----------------------------------------------------------------------------
# API: Shell (CAUTION)
# -----------------------------------------------------------------------------

@app.route("/shell", methods=["POST"])
def run_shell():
    """
    Execute a shell command on the host (use with care; gated by SHELL_ENABLED).

    Body:
        {"cmd": "...", "timeout": seconds (1..300)}

    Returns:
        JSON with stdout/stderr (capped), exit code, elapsed, and command run.
    """
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
        timeout = max(1, min(int(timeout), 300))
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


# -----------------------------------------------------------------------------
# Web UI
# -----------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def index():
    """Serve the main HTML UI."""
    return render_template("index.html")


@app.route("/static/<path:path>", methods=["GET"])
def send_static(path):
    """Serve static assets from /static."""
    return send_from_directory(app.static_folder, path)


# -----------------------------------------------------------------------------
# Entrypoint
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    # Use debug=True for live reload during development; turn off on the Pi.
    app.run(host="0.0.0.0", port=8000, debug=True)
