import os, json

try:
    from .sensors.INA219 import ina219
except Exception as e:
    ina219 = None

try:
    import board
except Exception as e:
    board = None

try:
    import busio
except Exception as e:
    busio = None

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
    log_files = os.listdir(LOG_DIR)
    for file in log_files[:-4]:
        file_path = os.path.join(LOG_DIR, file)
        os.remove(file_path)

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

    # INA219
    if not DEVELOPMENT_MODE:
        I2C = busio.I2C(board.SCL, board.SDA)
        INA = ina219(I2C)
