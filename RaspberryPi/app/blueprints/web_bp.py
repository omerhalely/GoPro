from flask import Blueprint, render_template, send_from_directory, current_app

bp = Blueprint("web", __name__)

@bp.route("/", methods=["GET"])
def index():
    """Serve the main HTML UI."""
    return render_template("index.html")


@bp.route("/static/<path:path>", methods=["GET"])
def send_static(path):
    """Serve static assets from /static."""
    return send_from_directory(current_app.static_folder, path)
