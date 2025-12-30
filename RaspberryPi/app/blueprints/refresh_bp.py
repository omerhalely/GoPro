from flask import Blueprint, current_app, jsonify
import subprocess
from pathlib import Path
from ..core.logger import _log


bp = Blueprint("refresh", __name__)


@bp.route("/refresh", methods=["POST"])
def refresh():
    config = current_app.config
    state = current_app.extensions["state"]

    if config["DEVELOPMENT_MODE"]:
        _log(config, state, "INFO", "refresh():Refresh is not available in dev mode")
        return jsonify({
            "ok": True,
            "dev": config["DEVELOPMENT_MODE"],
            "reset": True
        })
    else:
        _log(config, state, "INFO",
             "refresh():Refreshing software | Mode:{'Debug' if current_app.debug else 'Production'}")
        try:
            if current_app.debug:
                Path(__file__).touch()
            else:
                subprocess.Popen(["sudo", "systemctl", "restart", "flask_app.service"])
            return jsonify({
                "ok": True,
                "dev": config["DEVELOPMENT_MODE"],
                "reset": True
            })

        except Exception as e:
            _log(config, state, "ERROR", f"refresh():Failed running the bash file: {e}")
            return  jsonify({
                "ok": False,
                "dev": config["DEVELOPMENT_MODE"],
                "reset": False
            })


