import subprocess
import time
from flask import Blueprint, jsonify, request, current_app
from ..core.logger import _log

bp = Blueprint("network", __name__)

# Mock state for development mode
MOCK_MODE = "ap"

def run_command(cmd_list, timeout=5):
    try:
        res = subprocess.run(
            cmd_list, capture_output=True, text=True, timeout=timeout
        )
        return res.returncode == 0, res.stdout.strip()
    except Exception:
        return False, ""

@bp.route("/network/status", methods=["GET"])
def get_network_status():
    """
    Check current network status (AP vs WiFi).
    Returns JSON: { "mode": "ap"|"wifi"|"unknown", "connected": bool, "ssid": str }
    """
    config = current_app.config

    # --- DEVELOPMENT MODE MOCK ---
    if config.get("DEVELOPMENT_MODE"):
        global MOCK_MODE
        return jsonify({
            "mode": MOCK_MODE,
            "connected": True,  # Always white in debug mode
            "ssid": "DevMode"
        })
    # -----------------------------

    # 1. Check if AP is active
    ap_active, _ = run_command(["systemctl", "is-active", "hostapd"])
    if ap_active:
        # Check for connected clients
        # "iw dev wlan0 station dump" returns output if clients connected
        # We just check if stdout is non-empty
        ok, out = run_command(["iw", "dev", "wlan0", "station", "dump"])
        connected = (len(out) > 10) # arbitrary length check for meaningful output
        return jsonify({
            "mode": "ap",
            "connected": connected,
            "ssid": "PiCam-AP"
        })

    # 2. Check if WiFi is active
    wifi_active, _ = run_command(["systemctl", "is-active", "wpa_supplicant"])
    if wifi_active:
        # Check connection details
        # iwgetid -r prints SSID
        ok, ssid = run_command(["iwgetid", "-r"])
        return jsonify({
            "mode": "wifi",
            "connected": bool(ok and ssid),
            "ssid": ssid or ""
        })

    return jsonify({"mode": "unknown", "connected": False, "ssid": ""})


@bp.route("/network/switch", methods=["POST"])
def switch_network():
    """
    Switch network mode.
    Body: { "mode": "ap" | "wifi" }
    """
    config = current_app.config
    st = current_app.extensions["state"]
    
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")

    if mode not in ("ap", "wifi"):
        return jsonify({"error": "Invalid mode"}), 400

    _log(config, st, "INFO", f"Network switch requested to: {mode}")

    # --- DEVELOPMENT MODE MOCK ---
    if config.get("DEVELOPMENT_MODE"):
        global MOCK_MODE
        MOCK_MODE = mode
        msg = f"Simulated switch to {mode}"
        _log(config, st, "INFO", msg)
        return jsonify({"ok": True, "message": msg})
    # -----------------------------

    # Execute bash scripts
    script = "ap_enable.sh" if mode == "ap" else "wifi_enable.sh"
    # Assuming bash scripts are in ./bash/ relative to CWD
    cmd_path = f"./bash/{script}"

    # These scripts might take time (restarting services)
    # We run them blocking for simplicity, but in production maybe async?
    # Given they restart networking, the response might fail to reach client if network drops.
    # But usually AP->Wifi or Wifi->AP preserves the interface long enough or we rely on client polling.
    
    # Actually, we should probably return immediately and run in background, 
    # but the client expects confirmation. 
    # Let's try synchronous with a generous timeout.
    
    try:
        subprocess.Popen(["bash", cmd_path])
        # We don't wait for completion because it kills the network interface 
        # and we might lose the ability to reply.
        # Sending success immediately implies "Command started".
        return jsonify({"ok": True, "message": f"Switching to {mode}..."})
    except Exception as e:
        _log(config, st, "ERROR", f"Failed to start switch script: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
