from flask import Blueprint, current_app, jsonify, request, Response
from ..core.logger import _log
import time, threading, os


bp = Blueprint("capture", __name__)


def _run_capture_thread(app) -> None:
    """
    Background thread entry point that starts a video recording until _stop_evt is set.

    Behavior:
      - Ensures output directory exists
      - Chooses bitrate heuristically based on CURRENT_VIDEO_RES
      - Delegates to VideoCapture.video_capture(...) when not in DEV
      - On exit, marks recording state as stopped
    """
    config = app.config
    state = app.extensions["state"]

    save_dir = os.path.abspath(state.CURRENT_SAVE_DIR)
    try:
        # Ensure output dir exists (fail gracefully)
        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception as e:
            _log(config, state, "ERROR", f"image:capture failed: {e}")
            return

        print(f"[capture] Saving video to: {save_dir}")

        if config["DEVELOPMENT_MODE"]:
            # Simulate recording
            while not state._stop_evt.is_set():
                time.sleep(0.25)
        else:
            # Ensure no preview instance conflicts with recording
            if state._picam2 is not None:
                try:
                    state._picam2.stop()
                except Exception:
                    pass
                try:
                    state._picam2.close()
                except Exception:
                    pass
                state._picam2 = None

            # Simple bitrate map
            w, h = int(state.CURRENT_VIDEO_RES[0]), int(state.CURRENT_VIDEO_RES[1])
            if (w, h) == (320, 240):
                bitrate = 1_000_000
            elif (w, h) == (1280, 960):
                bitrate = 10_000_000
            else:
                bitrate = 3_000_000  # default for 640x480

            # Call user module (hardware encode to MP4 recommended)
            if config["video_capture"] is None:
                _log(config, state, "ERROR", "[capture][error] VideoCapture.video_capture not available")
                return

            config["video_capture"](
                output_dir=save_dir,
                stop_evt=state._stop_evt,
                width=w,
                height=h,
                fps=int(state.CURRENT_VIDEO_FPS),
                bitrate=int(bitrate),
            )
    finally:
        # Mark as not running even on error or stop
        with state._state_lock:
            state._is_running = False
        state._stop_evt.clear()


@bp.route("/start", methods=["GET"])
def start_capture():
    """
    Start video capture in a background thread.

    Returns:
        JSON: {"status": "started", "started_ts": <epoch>, "save_dir": <dir>}
              or an error if already running.
    """
    config = current_app.config
    st = current_app.extensions["state"]
    with st._state_lock:
        if st._is_running:
            return jsonify({"error": "Capture already running"}), 409
        st._stop_evt.clear()
        st._is_running = True
        _log(config, st, "INFO",
             f"capture:start save_dir='{st.CURRENT_SAVE_DIR}' res={st.CURRENT_VIDEO_RES} fps={st.CURRENT_VIDEO_FPS}")
        st._last_start_ts = int(time.time())
        _capture_thread = threading.Thread(target=_run_capture_thread, args=(current_app._get_current_object(),), daemon=True)
        _capture_thread.start()
    return jsonify({"status": "started", "started_ts": st._last_start_ts, "save_dir": st.CURRENT_SAVE_DIR})


@bp.route("/stop", methods=["GET"])
def stop_capture():
    """
    Signal the background capture thread to stop.

    Returns:
        JSON: {"status": "stop signaled"}
    """
    config = current_app.config
    st = current_app.extensions["state"]
    st._stop_evt.set()
    _log(config, st, "INFO", "capture:stop signaled")
    return jsonify({"status": "stop signaled"})


@bp.route("/status", methods=["GET"])
def status():
    """
    Return current capture state and configuration.

    Returns:
        JSON: {"running": bool, "started_ts": int|None, "save_dir": str}
    """
    st = current_app.extensions["state"]
    with st._state_lock:
        return jsonify({"running": st._is_running, "started_ts": st._last_start_ts, "save_dir": st.CURRENT_SAVE_DIR})


@bp.route("/capture_image", methods=["POST"])
def capture_image_endpoint():
    """
    Capture a still image and save it under CURRENT_SAVE_DIR.

    Returns:
        JSON:
          - {"ok": True, "path": "<full path>", "dev": False} on success (hardware)
          - {"ok": True, "path": "<full path>", "dev": True} in DEV fallback
          - {"ok": False, "error": "..."} on failure
    """
    config = current_app.config
    st = current_app.extensions["state"]
    save_dir = os.path.abspath(st.CURRENT_SAVE_DIR)

    # Ensure directory exists
    try:
        os.makedirs(save_dir, exist_ok=True)
    except Exception as e:
        _log(config, st, "ERROR", f"image:capture failed: {e}")
        return jsonify({"ok": False, "error": f"Cannot create directory: {e}"}), 500

    # Call real capture if available
    try:
        if config["image_capture"] is not None and not config["DEVELOPMENT_MODE"]:
            path = config["image_capture"](save_dir)  # your function should return full path
            if not path:
                return jsonify({"ok": False, "error": "capture_image() returned no path"}), 500
            _log(config, st, "INFO", f"image:capture path='{path}'")
            return jsonify({"ok": True, "path": path, "dev": False})
        else:
            # DEV fallback: return a predictable filename (not actually created here)
            ts = int(time.time())
            fname = f"snapshot_{ts}.jpg"
            fpath = os.path.join(save_dir, fname)
            _log(config, st, "INFO", f"image:capture path='{fpath}'")
            return jsonify({"ok": True, "path": fpath, "dev": True})
    except Exception as e:
        _log(config, st, "ERROR", f"image:capture failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500