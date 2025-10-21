import os
import io
from flask import Blueprint, current_app, jsonify, request
from ..core.logger import _log


bp = Blueprint("log", __name__)


@bp.route("/log", methods=["GET"])
def get_log():
    """
    Return tail of the current log file (read-only).
    JSON: { ok, path, started_ts, reset_hours, size, mtime, text }
    """
    config = current_app.config
    state = current_app.extensions["state"]
    try:
        path = state._log_path
        try:
            st = os.stat(path)
            size = st.st_size
            mtime = st.st_mtime
        except FileNotFoundError:
            size = 0
            mtime = None

        text = ""
        if os.path.exists(path) and os.path.isfile(path):
            with open(path, "rb") as f:
                if size > state._log_max_return_bytes:
                    f.seek(-state._log_max_return_bytes, io.SEEK_END)
                    text = f.read().decode("utf-8", errors="replace")
                    text = "[…truncated…]\n" + text
                else:
                    text = f.read().decode("utf-8", errors="replace")

        return jsonify({
            "ok": True,
            "path": path,
            "started_ts": int(state._log_started.timestamp()),
            "reset_hours": state._log_reset_hours,
            "size": size,
            "mtime": mtime,
            "text": text
        })
    except Exception as e:
        _log(config, state, "ERROR", f"log:get failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/log/config", methods=["POST", "GET"])
def log_config():
    """
    GET -> { ok, reset_hours }
    POST -> { ok, reset_hours } with body: { "reset_hours": int(1..720) }
    """
    config = current_app.config
    st = current_app.extensions["state"]
    if request.method == "GET":
        return jsonify({"ok": True, "reset_hours": st._log_reset_hours})

    try:
        body = request.get_json(force=True, silent=True) or {}
        hrs = int(body.get("reset_hours", st._log_reset_hours))
        hrs = max(1, min(hrs, 720))  # 1h .. 30d
        st._log_reset_hours = hrs
        _log(config, st, "INFO", f"log:reset_hours set to {hrs}")
        return jsonify({"ok": True, "reset_hours": st._log_reset_hours})
    except Exception as e:
        _log(config, st, "ERROR", f"log:config error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 400