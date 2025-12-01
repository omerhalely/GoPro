import datetime as dt
import os, threading
from typing import Optional

try:
    import RPi.GPIO as GPIO
except Exception:
    GPIO = None

class AppState:
    def __init__(self, config):
        # Logger
        self._log_max_return_bytes = 200 * 1024
        self._log_started = dt.datetime.now()
        self._log_reset_hours = config["LOG_RESET_HOURS_DEFAULT"]
        self._log_path = os.path.join(config["LOG_DIR"], f"log_{self._log_started.strftime('%Y%m%d_%H%M%S')}.txt")
        os.makedirs(os.path.dirname(self._log_path) or ".", exist_ok=True)

        # CPU
        self._prev_total = None
        self._prev_idle = None

        # LED
        self.LED_ON = True
        self.LED_PIN = config["LED_GPIO_PIN"]
        if GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.LED_PIN, GPIO.OUT)

        # Files
        self.CURRENT_SAVE_DIR = config["DEFAULT_SAVE_DIR"]

        # Camera
        self._picam2 = None
        self._picam_lock = threading.Lock()
        self._preview_fps = 25

        # Preview controls
        self._preview_ctrls = dict(config["DEFAULT_PREVIEW_CTRLS"])

        # Capture video
        self._state_lock = threading.Lock()
        self._is_running: bool = False
        self._stop_evt = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._last_start_ts: Optional[int] = None

        # Resolutions
        self.CURRENT_IMAGE_RES = config["IMAGE_RES_DEFAULT"]
        self.CURRENT_VIDEO_RES = config["VIDEO_RES_DEFAULT"]
        self.CURRENT_VIDEO_FPS = config["VIDEO_FPS_DEFAULT"]
