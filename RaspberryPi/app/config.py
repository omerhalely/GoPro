import os

class AppConfig:
    # Core toggles
    DEVELOPMENT_MODE = True
    SHELL_ENABLED = True

    try:
        from picamera2 import Picamera2
    except Exception as e:
        if not DEVELOPMENT_MODE:
            print("[Picamera2 import error]", e)
        Picamera2 = None  # type: ignore
    try:
        from .sensors.VideoCapture import video_capture  # def video_capture(output_dir,...)
    except Exception as e:
        if not DEVELOPMENT_MODE:
            print("[VideoCapture import error]", e)
        video_capture = None
    try:
        from .sensors.ImageCapture import image_capture  # def image_capture(save_dir) -> str
    except Exception as e:
        if not DEVELOPMENT_MODE:
            print("[ImageCapture import error]", e)
        image_capture = None

    # Paths
    DEFAULT_SAVE_DIR = "./outputs"
    os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)

    # Video/Image defaults
    IMAGE_RES_DEFAULT = (640, 480)
    VIDEO_RES_DEFAULT = (640, 480)
    VIDEO_FPS_DEFAULT = 25

    # Shell safety
    SHELL_TIMEOUT_DEFAULT = 15
    SHELL_MAX_CHARS = 100_000

    # Logger
    LOG_DIR = os.path.join(os.getcwd(), "logs")
    os.makedirs(LOG_DIR, exist_ok=True)

    # Rotate every N hours (no thread; checked on each write)
    LOG_RESET_HOURS_DEFAULT = 24

    # Preview defaults
    DEFAULT_PREVIEW_CTRLS = {
        "AeEnable": True,  # auto exposure
        "ExposureTime": None,  # μs (manual only if AeEnable=False)
        "AnalogueGain": None,  # 1.0..16.0 (manual only if AeEnable=False)
        "DigitalGain": None,  # 1.0..16.0 (manual only if AeEnable=False)
        "Brightness": 0.0,  # -1.0..+1.0
        "Contrast": 1.0,  # 0..32
        "Saturation": 1.0,  # 0..32
        "Sharpness": 1.0,  # 0..16
    }
