import time
import platform
import subprocess
from ..core.logger import _log
from flask import Blueprint, current_app, jsonify, request


bp = Blueprint("shell", __name__)


@bp.route("/shell", methods=["POST"])
def run_shell():
    """
    Execute a shell command on the host (use with care; gated by SHELL_ENABLED).

    Body:
        {"cmd": "...", "timeout": seconds (1..300)}

    Returns:
        JSON with stdout/stderr (capped), exit code, elapsed, and command run.
    """
    config = current_app.config
    st = current_app.extensions["state"]

    if not config["SHELL_ENABLED"]:
        return jsonify({"error": "Shell disabled on server"}), 403

    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    cmd = (body.get("cmd") or "").strip()
    if not cmd:
        return jsonify({"error": "Missing 'cmd'"}), 400

    timeout = body.get("timeout") or config["SHELL_TIMEOUT_DEFAULT"]
    try:
        timeout = max(1, min(int(timeout), 300))
    except Exception:
        timeout = config["SHELL_TIMEOUT_DEFAULT"]

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
        _log(config, st, "ERROR", f"run_shell():Timeout cmd='{cmd}'")
        return jsonify({
            "ok": False, "timeout": True, "code": None,
            "elapsed_sec": round(time.time() - start, 3),
            "stdout": (e.stdout or "")[:config["SHELL_MAX_CHARS"]],
            "stderr": (e.stderr or "")[:config["SHELL_MAX_CHARS"]],
            "ran": exec_cmd if 'exec_cmd' in locals() else cmd,
        }), 504

    stdout = (res.stdout or "")[:config["SHELL_MAX_CHARS"]]
    stderr = (res.stderr or "")[:config["SHELL_MAX_CHARS"]]

    _log(config, st, "INFO", f"run_shell():Run cmd='{cmd}' timeout={timeout}s")
    return jsonify({
        "ok": res.returncode == 0,
        "code": res.returncode,
        "elapsed_sec": round(elapsed, 3),
        "stdout": stdout,
        "stderr": stderr,
        "ran": exec_cmd,
    })