import os, json

class AppConfig:
    configurations_path = os.path.join(os.path.abspath(os.path.join(os.getcwd(), ".")), "configurations.json")
    with open(configurations_path, "r") as file:
        cfg = json.load(file)

    # Core toggles
    DEVELOPMENT_MODE = cfg["development_mode"]
    SHELL_ENABLED = cfg["shell_enabled"]

    # Paths
    DEFAULT_SAVE_DIR = cfg["default_save_dir"]
    os.makedirs(DEFAULT_SAVE_DIR, exist_ok=True)

    # Video/Image defaults
    IMAGE_RES_DEFAULT = tuple(cfg["image_res_default"])
    VIDEO_RES_DEFAULT = tuple(cfg["video_res_default"])
    VIDEO_FPS_DEFAULT = cfg["video_fps_default"]

    # Shell safety
    SHELL_TIMEOUT_DEFAULT = cfg["shell_timeout_default"]
    SHELL_MAX_CHARS = cfg["shell_max_chars"]

    # Logger
    LOG_DIR = cfg["log_dir"]
    os.makedirs(LOG_DIR, exist_ok=True)

    # Rotate every N hours (no thread; checked on each write)
    LOG_RESET_HOURS_DEFAULT = cfg["log_reset_hours_default"]

    # Preview defaults
    DEFAULT_PREVIEW_CTRLS = {
        "AeEnable": cfg["AeEnable"],  # auto exposure
        "ExposureTime": cfg["ExposureTime"],  # μs (manual only if AeEnable=False)
        "AnalogueGain": cfg["AnalogueGain"],  # 1.0..16.0 (manual only if AeEnable=False)
        "DigitalGain": cfg["DigitalGain"],  # 1.0..16.0 (manual only if AeEnable=False)
        "Brightness": cfg["Brightness"],  # -1.0..+1.0
        "Contrast": cfg["Contrast"],  # 0..32
        "Saturation": cfg["Saturation"],  # 0..32
        "Sharpness": cfg["Sharpness"]  # 0..16
    }

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
