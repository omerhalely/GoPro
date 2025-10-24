from typing import Optional, Tuple, Union, List
import os
from .logger import _log


def _res_to_str(res: Union[Tuple[int, int], List[int]]) -> str:
    """Convert (w,h) to 'WxH' string."""
    try:
        w, h = int(res[0]), int(res[1])
        return f"{w}x{h}"
    except Exception:
        return "—"


def _parse_res_str(s: str) -> Optional[Tuple[int, int]]:
    """Parse 'WxH' into (w,h) ints. Returns None on failure."""
    try:
        parts = s.lower().split("x")
        if len(parts) != 2:
            return None
        w, h = int(parts[0]), int(parts[1])
        if w <= 0 or h <= 0:
            return None
        return (w, h)
    except Exception:
        return None


def _safe_under_base(base: str, rel: str) -> str:
    """
    Resolve a user-supplied relative path under base, ensuring no directory traversal.

    Raises:
        ValueError: if resolved path escapes base.
    """
    rel = (rel or "").strip().lstrip("/\\")
    target = os.path.abspath(os.path.join(base, rel))
    if not target.startswith(os.path.abspath(base)):
        raise ValueError("Invalid path")
    return target


def _apply_preview_controls_if_running(config, state) -> bool:
    """Apply _preview_ctrls to the running preview camera, if present."""
    with state._picam_lock:
        if state._picam2 is None:
            return False
        try:
            state._picam2.set_controls(state._preview_ctrls)
            return True
        except Exception as e:
            _log(config, state, "ERROR", f"_apply_preview_controls_if_running():Failed to apply preview controls: {e}")
            return False


def _sanitize_and_merge_preview_ctrls(state, update: dict) -> dict:
    """
    Merge user-provided values into _preview_ctrls with clamping.
    Auto-disables AE if manual exposure/gains are changed (unless AeEnable is explicitly included).
    """
    def to_bool(v):
        if isinstance(v, bool): return v
        s = str(v).lower()
        return s in ("1", "true", "yes", "on")

    def to_int(v):
        try: return int(v)
        except: return None

    def to_float(v):
        try: return float(v)
        except: return None

    merged = dict(state._preview_ctrls)

    if "AeEnable" in update:
        merged["AeEnable"] = to_bool(update["AeEnable"])

    if "ExposureTime" in update:
        et = to_int(update["ExposureTime"])
        if et is not None:
            merged["ExposureTime"] = max(20, min(et, 2_000_000))  # 20µs..2s

    if "AnalogueGain" in update:
        ag = to_float(update["AnalogueGain"])
        if ag is not None:
            merged["AnalogueGain"] = max(1.0, min(ag, 16.0))

    if "DigitalGain" in update:
        dg = to_float(update["DigitalGain"])
        if dg is not None:
            merged["DigitalGain"] = max(1.0, min(dg, 16.0))

    if "Brightness" in update:
        b = to_float(update["Brightness"])
        if b is not None:
            merged["Brightness"] = max(-1.0, min(b, 1.0))

    if "Contrast" in update:
        c = to_float(update["Contrast"])
        if c is not None:
            merged["Contrast"] = max(0.0, min(c, 32.0))

    if "Saturation" in update:
        s = to_float(update["Saturation"])
        if s is not None:
            merged["Saturation"] = max(0.0, min(s, 32.0))

    if "Sharpness" in update:
        sh = to_float(update["Sharpness"])
        if sh is not None:
            merged["Sharpness"] = max(0.0, min(sh, 16.0))

    # If user tweaked manual exposure/gain but didn't specify AeEnable, turn AE off.
    if any(k in update for k in ("ExposureTime", "AnalogueGain", "DigitalGain")) \
       and "AeEnable" not in update and merged["AeEnable"]:
        merged["AeEnable"] = False

    state._preview_ctrls = merged
    return merged
