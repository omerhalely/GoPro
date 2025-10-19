from __future__ import annotations
from flask import Flask
from .config import AppConfig
from .core.state import AppState

# Blueprints
from .blueprints.web_bp import bp as web_bp
from .blueprints.config_bp import bp as config_bp
from .blueprints.metrics_bp import bp as metrics_bp
from .blueprints.files_bp import bp as files_bp
from .blueprints.capture_bp import bp as capture_bp
from .blueprints.preview_bp import bp as preview_bp
from .blueprints.power_bp import bp as power_bp
from .blueprints.shell_bp import bp as shell_bp
from .blueprints.log_bp import bp as log_bp

def create_app() -> Flask:
    app = Flask(__name__, static_folder="../static", template_folder="templates")

    # Load config (env overrides allowed)
    app.config.from_object(AppConfig())

    # Attach shared state and logger
    app.extensions = getattr(app, "extensions", {})
    app.extensions["state"] = AppState(app.config)

    # Register blueprints
    app.register_blueprint(web_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(metrics_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(capture_bp)
    app.register_blueprint(preview_bp)
    app.register_blueprint(power_bp)
    app.register_blueprint(shell_bp)
    app.register_blueprint(log_bp)

    # Example error logging hook (concise)
    # @app.errorhandler(Exception)
    # def _on_error(err):
    #     app.extensions["applog"].error("unhandled_exception", {"err": repr(err)})
    #     # You can re-raise or return a generic JSON here if you want
    #     raise err

    return app
