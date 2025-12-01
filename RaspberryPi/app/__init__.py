from __future__ import annotations
from flask import Flask
from .config import AppConfig
from .core.state import AppState
from .core.logger import _log

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
from .blueprints.refresh_bp import bp as refresh_bp

def create_app(dev_mode: bool) -> Flask:
    app = Flask(__name__, static_folder="../static", template_folder="templates")

    # Load config (env overrides allowed)
    app.config.from_object(AppConfig())
    app.config["DEVELOPMENT_MODE"] = dev_mode

    # Attach shared state and logger
    app.extensions = getattr(app, "extensions", {})
    app.extensions["state"] = AppState(app.config)

    config = app.config
    state = app.extensions["state"]
    _log(config, state, "INFO", f"Building Application : {'DEVELOPMENT MODE' if dev_mode else 'PRODUCTION MODE'}")

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
    app.register_blueprint(refresh_bp)

    _log(config, state, "INFO", "Built Application Successfully")
    _set_led(config, state, state.LED_ON)

    if app.config["INA"]:
        if app.config["INA"].get_status():
            _log(config, state, "INFO", "INA219 Found")
        else:
            _log(config, state, "WARNING", "INA219 Not Found")
    return app
