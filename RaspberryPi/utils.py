import os


def _parse_res_str(s):
    """
    '640x480' -> (640, 480). Returns None if invalid.
    """
    try:
        s = (s or "").lower().strip().replace(" ", "")
        if "x" not in s:
            return None
        w, h = s.split("x", 1)
        w, h = int(w), int(h)
        if w <= 0 or h <= 0 or w > 7680 or h > 4320:  # sanity guard up to 8K
            return None
        return (w, h)
    except Exception:
        return None


def _res_to_str(res):
    try:
        w, h = int(res[0]), int(res[1])
        return f"{w}x{h}"
    except Exception:
        return ""


def _safe_under_base(base: str, rel: str) -> str:
    """Resolve a user path and ensure it stays under base directory."""
    rel = (rel or "").strip().lstrip("/\\")
    target = os.path.abspath(os.path.join(base, rel))
    if not target.startswith(base):
        raise ValueError("Invalid path")
    return target
