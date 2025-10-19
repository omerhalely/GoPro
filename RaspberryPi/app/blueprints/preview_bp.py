from flask import Blueprint, current_app, jsonify, request, Response
from ..core.hardware import _ensure_picam2
from ..core.logger import _log
from ..core.utils import _apply_preview_controls_if_running, _sanitize_and_merge_preview_ctrls
import cv2
import time

bp = Blueprint("preview", __name__)


@bp.route("/preview.mjpg", methods=["GET"])
def preview_mjpg():
    """
    Stream a MJPEG preview from the camera using multipart/x-mixed-replace.

    DEV mode:
        Returns 503 since no real camera is used.
    PROD:
        Uses a dedicated Picamera2 instance configured for BGR888 and encodes
        each frame as JPEG (quality=80).
    """
    config = current_app.config
    st = current_app.extensions["state"]

    if config["DEVELOPMENT_MODE"]:
        return jsonify({"ok": False, "error": "Preview disabled in DEV"}), 503

    try:
        cam = _ensure_picam2(st, config["Picamera2"])
    except Exception as e:
        _log(config, st, "ERROR", f"image:capture failed: {e}")
        return jsonify({"ok": False, "error": f"camera init failed: {e}"}), 503

    def gen():
        delay = 1.0 / max(1, st._preview_fps)
        while True:
            try:
                bgr = cam.capture_array()  # shape (H,W,3), dtype=uint8
                ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                if not ok:
                    time.sleep(delay)
                    continue
                jpg = buf.tobytes()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" +
                    jpg + b"\r\n"
                )
            except GeneratorExit:
                break
            except Exception:
                time.sleep(delay)
                continue

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

@bp.route("/preview_controls", methods=["GET", "POST"])
def preview_controls():
    """
    Get or set live preview controls.

    GET  -> {"ok":true, "controls":{...}, "applied": bool, "dev": bool}
    POST -> accepts any subset of:
        AeEnable (bool), ExposureTime (int μs), AnalogueGain (float),
        DigitalGain (float), Brightness (float), Contrast (float),
        Saturation (float), Sharpness (float)
        Special: {"reset": true} restores DEFAULT_PREVIEW_CTRLS
    """
    config = current_app.config
    st = current_app.extensions["state"]
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "controls": st._preview_ctrls,
            "applied": st._picam2 is not None,
            "dev": config["DEVELOPMENT_MODE"]
        })

    body = request.get_json(force=True, silent=True) or {}

    # Reset to defaults
    if body.get("reset"):
        st._preview_ctrls = dict(config["DEFAULT_PREVIEW_CTRLS"])
        applied = _apply_preview_controls_if_running(config, st)
        return jsonify({
            "ok": True,
            "controls": st._preview_ctrls,
            "applied": applied,
            "dev": config["DEVELOPMENT_MODE"],
            "reset": True
        })

    merged = _sanitize_and_merge_preview_ctrls(st, body)
    applied = _apply_preview_controls_if_running(config, st)
    return jsonify({
        "ok": True,
        "controls": merged,
        "applied": applied,
        "dev": config["DEVELOPMENT_MODE"]
    })