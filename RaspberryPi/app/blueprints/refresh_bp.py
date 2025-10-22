from flask import Blueprint, current_app, jsonify
import os, subprocess
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
        bash_path = os.path.join(os.getcwd(), "bash", "refresh_app.sh")
        _log(config, state, "INFO", "refresh():Refreshing software")
        subprocess.run(
            ["bash", bash_path],
            capture_output=False,
            text=True
        )
        return jsonify({
            "ok": True,
            "dev": config["DEVELOPMENT_MODE"],
            "reset": True
        })


