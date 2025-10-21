import os
import subprocess
from typing import Optional, Tuple
from flask.config import Config
from .state import AppState
from .utils import _effective_controls_dict

try:
    from picamera2 import Picamera2
except Exception as e:
    Picamera2 = None


def _randf(lo: float, hi: float) -> float:
    """Return a random float in [lo, hi] without importing random."""
    r = int.from_bytes(os.urandom(8), "big") / (1 << 64)
    return lo + (hi - lo) * r


def _read_cpu_temp_c(config: Config) -> Optional[float]:
    """Return CPU temperature in °C, or None if unavailable (DEV may simulate)."""
    if config["DEVELOPMENT_MODE"]:
        return round(_randf(38.0, 72.0), 1)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return float(f.read().strip()) / 1000.0
    except Exception:
        return None


def _read_gpu_temp_c(config: Config) -> Optional[float]:
    """Return GPU temperature in °C via vcgencmd, or None if unavailable."""
    if config["DEVELOPMENT_MODE"]:
        return round(_randf(40.0, 70.0), 1)
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"], text=True, timeout=1)
        if "temp=" in out:
            return float(out.split("temp=")[1].split("'")[0])
    except Exception:
        pass
    return None


def _read_cpu_util_percent(config: Config, state:AppState) -> Optional[float]:
    """
    Return CPU utilization percent based on /proc/stat deltas, or None on first call.
    DEV mode returns simulated values.
    """
    if config["DEVELOPMENT_MODE"]:
        base = _randf(8.0, 35.0)
        spike = _randf(0, 1)
        return round(base + (50.0 if spike > 0.95 else 0.0), 1)
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return None
        parts = [float(x) for x in line.split()[1:11]]
        user, nice, system, idle, iowait, irq, softirq, steal, *_ = (parts + [0] * 10)[:8]
        idle_all = idle + iowait
        non_idle = user + nice + system + irq + softirq + steal
        total = idle_all + non_idle
        if state._prev_total is None:
            _prev_total, _prev_idle = total, idle_all
            return None
        totald = total - state._prev_total
        idled = idle_all - state._prev_idle
        _prev_total, _prev_idle = total, idle_all
        if totald <= 0:
            return None
        return max(0.0, min(100.0, (totald - idled) * 100.0 / totald))
    except Exception:
        return None


def _read_ram_percent_used(config: Config) -> Optional[float]:
    """Return RAM used percent by parsing /proc/meminfo, or None if unavailable."""
    if config["DEVELOPMENT_MODE"]:
        return round(_randf(20.0, 85.0), 1)
    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                meminfo[k] = float(v.strip().split()[0])  # kB
        total = meminfo.get("MemTotal")
        avail = meminfo.get("MemAvailable")
        if not total or not avail:
            return None
        used = total - avail
        return used * 100.0 / total
    except Exception:
        return None


def _read_disk_free_percent(config: Config) -> Optional[float]:
    """Return free disk percent for filesystem containing 'path', or None."""
    if config["DEVELOPMENT_MODE"]:
        return round(_randf(35.0, 95.0), 1)
    try:
        st = os.statvfs(os.getcwd())
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if total <= 0:
            return None
        return free * 100.0 / total
    except Exception:
        return None


def _read_cpu_freq_mhz(config: Config) -> Optional[float]:
    """Return current CPU frequency in MHz, or None if unavailable."""
    if config["DEVELOPMENT_MODE"]:
        return round(_randf(600.0, 1500.0), 0)
    for p in (
        "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq",
        "/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq",
    ):
        try:
            with open(p) as f:
                v = f.read().strip()
                return (int(v) if v.isdigit() else float(v)) / 1000.0
        except Exception:
            continue
    return None


def _set_led(config: Config, state: AppState, on: bool) -> None:
    """Set LED state (placeholder; implement with GPIO if desired)."""
    state.LED_ON = bool(on)
    if config["DEVELOPMENT_MODE"]:
        return
    try:
        # TODO: implement actual GPIO control
        pass
    except Exception:
        pass


def _read_voltage_current(config: Config) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Return (current_A, voltage_V) from a sensor if present; DEV simulates."""
    if config["DEVELOPMENT_MODE"]:
        volts = round(_randf(4.80, 5.20), 3)
        amps = round(_randf(0.10, 2.50), 3)
        return amps, volts, volts * amps
    try:
        # TODO: read from e.g., INA219/INA260 if wired
        return None, None
    except Exception:
        return None, None


def _ensure_picam2(state: AppState):
    """
    (Re)create a lightweight Picamera2 instance configured for preview streaming.

    Returns:
        A started Picamera2 instance using BGR888 for OpenCV-friendly JPEG encoding.
    """
    with state._picam_lock:
        # Always reset to avoid conflicts with recording instance
        if state._picam2 is not None:
            try: state._picam2.stop()
            except Exception: pass
            try: state._picam2.close()
            except Exception: pass
            _picam2 = None

        if Picamera2 is None:
            raise Exception("Picamera2 is None")

        picam2 = Picamera2()
        width = int(state.CURRENT_VIDEO_RES[0])
        height = int(state.CURRENT_VIDEO_RES[1])

        # Start with current preview controls (skip Nones for manual fields)
        ctrl_init = _effective_controls_dict(state._preview_ctrls)

        config = picam2.create_preview_configuration(
            main={"size": (width, height), "format": "RGB888"},
            controls={
                "FrameRate": int(state.CURRENT_VIDEO_FPS),
                **ctrl_init
            }
        )
        picam2.configure(config)
        picam2.start()

        # Apply again post-start (some controls behave better this way)
        try:
            picam2.set_controls(ctrl_init)
        except Exception:
            pass

        state._picam2 = picam2
        return state._picam2