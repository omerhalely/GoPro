import time
from flask import Blueprint, current_app, jsonify
from ..core.hardware import (_read_cpu_temp_c, _read_gpu_temp_c, _read_cpu_util_percent, _read_ram_percent_used,
                           _read_disk_free_percent, _read_cpu_freq_mhz, _read_voltage_current)


bp = Blueprint("metrics", __name__)


@bp.route("/metrics", methods=["GET"])
def metrics():
    """
    Return a snapshot of system metrics for the UI graphs.

    Returns:
        JSON with timestamps and numeric fields for CPU/GPU temp, CPU util/clock,
        RAM used percent, disk free percent, and optional sensor (A/V).
    """
    config = current_app.config
    st = current_app.extensions["state"]
    ts = time.time()
    cpu_temp = _read_cpu_temp_c(config)
    gpu_temp = _read_gpu_temp_c(config)
    cpu_util = _read_cpu_util_percent(config, st)
    ram_used = _read_ram_percent_used(config)
    disk_free = _read_disk_free_percent(config)
    cpu_mhz = _read_cpu_freq_mhz(config)
    amps, volts, power = _read_voltage_current(config)

    def rnd(x, n=2): return None if x is None else round(x, n)
    return jsonify({
        "ts": ts,
        "sensors": {"current_a": rnd(amps, 3), "voltage_v": rnd(volts, 3), "power_w": rnd(power, 3)},
        "cpu": {"temp_c": rnd(cpu_temp, 1), "util_pct": rnd(cpu_util, 1), "freq_mhz": rnd(cpu_mhz, 0)},
        "gpu": {"temp_c": rnd(gpu_temp, 1)},
        "ram": {"used_pct": rnd(ram_used, 1)},
        "disk": {"free_pct": rnd(disk_free, 1), "path": st.CURRENT_SAVE_DIR}
    })