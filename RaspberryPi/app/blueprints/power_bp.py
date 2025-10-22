from flask import Blueprint, current_app, jsonify, request
import subprocess
from ..core.logger import _log


bp = Blueprint("power", __name__)


@bp.route("/power", methods=["POST"])
def power_action():
    """
    Perform a power action: reboot or shutdown (requires sudo on real Pi).

    Body:
        {"action": "reboot" | "shutdown"}

    DEV mode:
        Returns a simulated success without running any command.
    """
    config = current_app.config
    st = current_app.extensions["state"]
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}
    action = (body.get("action") or "").lower()
    if action not in ("reboot", "shutdown"):
        return jsonify({"ok": False, "error": "Invalid action (use 'reboot' or 'shutdown')"}), 400

    if config["DEVELOPMENT_MODE"]:
        return jsonify({"ok": True, "dev": True, "action": action, "message": f"Simulated {action} in DEV mode."})

    try:
        if action == "reboot":
            cmd = ["sudo", "reboot"]
        else:
            cmd = ["sudo", "shutdown", "-h", "now"]
        subprocess.Popen(cmd)  # do not wait
        return jsonify({"ok": True, "dev": False, "action": action, "message": f"{action} command sent."})
    except Exception as e:
        _log(config, st, "ERROR", f"power():Failed to restart/turn off the raspberrypi: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500