from flask import Blueprint, current_app, jsonify, request
from ..core.logger import _log
from ..core.utils import _res_to_str, _parse_res_str


bp = Blueprint("config", __name__)


@bp.route("/config", methods=["GET"])
def get_config():
    """
    Return current configuration and defaults for client UI.

    Returns:
        JSON with development_mode, directories, resolutions, FPS, LED.
    """
    config = current_app.config
    st = current_app.extensions["state"]
    return jsonify({
        "development_mode": config["DEVELOPMENT_MODE"],
        "save_dir_default": config["DEFAULT_SAVE_DIR"],
        "save_dir_current": st.CURRENT_SAVE_DIR,

        "image_res_default": _res_to_str(config["IMAGE_RES_DEFAULT"]),
        "image_res_current": _res_to_str(st.CURRENT_IMAGE_RES),
        "video_res_default": _res_to_str(config["VIDEO_RES_DEFAULT"]),
        "video_res_current": _res_to_str(st.CURRENT_VIDEO_RES),
        "video_fps_default": config["VIDEO_FPS_DEFAULT"],
        "video_fps_current": st.CURRENT_VIDEO_FPS,

        "led_on": False if config["DEVELOPMENT_MODE"] else False,
    })


@bp.route("/config", methods=["POST"])
def post_config():
    """
    Update mutable configuration from JSON body.

    Body (any optional):
        {
          "save_dir": "/path/to/save",
          "image_res": "WxH",
          "video_res": "WxH",
          "video_fps": int
        }

    Returns:
        JSON echoing the effective config after update.
    """
    config = current_app.config
    st = current_app.extensions["state"]
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    # Save dir
    save_dir = body.get("save_dir")
    if isinstance(save_dir, str) and save_dir.strip():
        st.CURRENT_SAVE_DIR = save_dir.strip()

    # Image resolution
    img_res = body.get("image_res")
    if isinstance(img_res, str):
        parsed = _parse_res_str(img_res)
        if parsed:
            st.CURRENT_IMAGE_RES = list(parsed)

    # Video resolution
    vid_res = body.get("video_res")
    if isinstance(vid_res, str):
        parsed = _parse_res_str(vid_res)
        if parsed:
            st.CURRENT_VIDEO_RES = list(parsed)

    # Video FPS
    fps = body.get("video_fps")
    try:
        if fps is not None:
            fps = int(fps)
            if 1 <= fps <= 120:
                st.CURRENT_VIDEO_FPS = fps
    except Exception:
        pass

    _log(config, st, "INFO", f"config:update save_dir='{st.CURRENT_SAVE_DIR}' img={_res_to_str(st.CURRENT_IMAGE_RES)} "
                             f"vid={_res_to_str(st.CURRENT_VIDEO_RES)} fps={st.CURRENT_VIDEO_FPS}")
    return jsonify({
        "ok": True,
        "save_dir_current": st.CURRENT_SAVE_DIR,
        "image_res_current": _res_to_str(st.CURRENT_IMAGE_RES),
        "video_res_current": _res_to_str(st.CURRENT_VIDEO_RES),
        "video_fps_current": st.CURRENT_VIDEO_FPS,
    })