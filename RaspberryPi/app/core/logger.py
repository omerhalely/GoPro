import os
import datetime as dt
from .state import AppState
from flask.config import Config


def _log_rotate_if_needed(config: Config,st: AppState, now: dt.datetime | None = None):
    """Rotate (start a new file) if the reset interval has elapsed."""
    now = now or dt.datetime.now()
    elapsed = (now - st._log_started).total_seconds() / 3600.0
    if elapsed >= max(1, float(st._log_reset_hours)):
        st._log_started = now
        st._log_path = os.path.join(config["LOG_DIR"], f"log_{st._log_started.strftime('%Y%m%d_%H%M%S')}.txt")
        try:
            with open(st._log_path, "w", encoding="utf-8") as f:
                f.write(f"=== New log started at {now.isoformat(timespec='seconds')} (reset_hours={st._log_reset_hours}) ===\n")
        except Exception:
            pass  # don't crash logger

def _log(config: Config, st: AppState, level: str, message: str):
    """Concise logger: rotate if needed, then append one line."""
    try:
        _log_rotate_if_needed(config, st)
        ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} [{level}] {message}\n"
        with open(st._log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        # Never break the app on logging failure
        pass