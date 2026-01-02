from flask import Blueprint, current_app, jsonify, request, Response
from ..core.logger import _log
from ..core.utils import _safe_under_base
from ..core.hardware import _read_disk_free_percent
import os, mimetypes, shutil, uuid


bp = Blueprint("files", __name__)


@bp.route("/files", methods=["GET"])
def list_files():
    """
    List files and directories under CURRENT_SAVE_DIR.

    Query params:
        path: str  (relative path inside CURRENT_SAVE_DIR; default root)

    Returns:
        JSON: { ok, base, path, entries:[{name,type,size,mtime,path}] }
              path is relative to base; entries sorted: directories first.
    """
    config = current_app.config
    state = current_app.extensions["state"]

    try:
        rel = (request.args.get("path") or "").strip().lstrip("/\\")
        base = os.path.abspath(state.CURRENT_SAVE_DIR)
        target = os.path.abspath(os.path.join(base, rel))

        # Security: must stay under base
        if not target.startswith(base):
            return jsonify({"ok": False, "error": "Invalid path"}), 400

        if not os.path.exists(target):
            return jsonify({"ok": False, "error": "Not found"}), 404

        entries = []
        try:
            names = os.listdir(target)
        except Exception as e:
            _log(config, state, "ERROR", f"list_files():Failed to load files: {e}")
            return jsonify({"ok": False, "error": f"Cannot list directory: {e}"}), 500

        names.sort(key=lambda n: (not os.path.isdir(os.path.join(target, n)), n.lower()))

        for name in names[:2000]:  # soft cap
            full = os.path.join(target, name)
            try:
                st = os.stat(full)
                entries.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(full) else "file",
                    "size": st.st_size if os.path.isfile(full) else None,
                    "mtime": st.st_mtime,
                    "path": os.path.relpath(full, base).replace("\\", "/")
                })
            except Exception:
                continue

        rel_out = "" if target == base else os.path.relpath(target, base).replace("\\", "/")
        return jsonify({
            "ok": True,
            "base": base,
            "path": rel_out,
            "entries": entries
        })
    except Exception as e:
        _log(config, state, "ERROR", f"list_files():Failed to list files: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/media", methods=["GET"])
def serve_media():
    """
    Serve files under CURRENT_SAVE_DIR with Range support (video seeking).

    Query params:
        path: str      (relative path inside CURRENT_SAVE_DIR)
        download: bool (if '1'/'true' => force Content-Disposition: attachment)

    Returns:
        Streaming Response with correct mimetype and range handling.
    """
    state = current_app.extensions["state"]

    rel = (request.args.get("path") or "").strip().lstrip("/\\")
    base = os.path.abspath(state.CURRENT_SAVE_DIR)
    target = os.path.abspath(os.path.join(base, rel))
    force_download = (request.args.get("download") in ("1", "true", "yes"))

    if not target.startswith(base):
        return jsonify({"ok": False, "error": "Invalid path"}), 400
    if not os.path.exists(target) or not os.path.isfile(target):
        return jsonify({"ok": False, "error": "Not found"}), 404

    file_size = os.path.getsize(target)
    mime, _ = mimetypes.guess_type(target)
    if not mime:
        mime = "application/octet-stream"

    def add_download_headers(rv: Response) -> Response:
        """Optionally force 'Save as' behavior."""
        if force_download:
            rv.headers.add("Content-Disposition", f'attachment; filename="{os.path.basename(target)}"')
        return rv

    range_header = request.headers.get("Range", None)
    if range_header:
        # bytes=START-END
        try:
            units, rng = range_header.split("=")
            if units.strip() != "bytes":
                raise ValueError
            start_end = rng.split("-")
            start = int(start_end[0]) if start_end[0] else 0
            end = int(start_end[1]) if len(start_end) > 1 and start_end[1] else file_size - 1
            start = max(0, start)
            end = min(end, file_size - 1)
            if start > end:
                start, end = 0, file_size - 1
        except Exception:
            start, end = 0, file_size - 1

        length = end - start + 1

        def generate():
            with open(target, "rb") as f:
                f.seek(start)
                chunk_size = 8192
                remaining = length
                while remaining > 0:
                    data = f.read(min(chunk_size, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        rv = Response(generate(), status=206, mimetype=mime, direct_passthrough=True)
        rv.headers.add("Content-Range", f"bytes {start}-{end}/{file_size}")
        rv.headers.add("Accept-Ranges", "bytes")
        rv.headers.add("Content-Length", str(length))
        return add_download_headers(rv)

    # No range: full file
    def generate_full():
        with open(target, "rb") as f:
            while True:
                data = f.read(8192)
                if not data:
                    break
                yield data

    rv = Response(generate_full(), mimetype=mime, direct_passthrough=True)
    rv.headers.add("Content-Length", str(file_size))
    rv.headers.add("Accept-Ranges", "bytes")
    return add_download_headers(rv)


@bp.route("/delete", methods=["POST"])
def delete_entry():
    """
    Delete file/folder under CURRENT_SAVE_DIR.

    Body (JSON):
        {
          "path": "relative/path/from/CURRENT_SAVE_DIR",
          "permanent": false  # default False => soft delete (move to .trash/)
        }

    Behavior:
        - Soft delete: move target into <CURRENT_SAVE_DIR>/.trash/<name_uuid>
        - Permanent:   remove file or recursively remove directory
        - Refuses to delete the root directory itself

    Returns:
        JSON: { ok, action: "moved_to_trash"|"deleted", path, disk_free_pct }
    """
    config = current_app.config
    state = current_app.extensions["state"]
    base = os.path.abspath(state.CURRENT_SAVE_DIR)
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    rel = (body.get("path") or "").strip()
    
    # Check if target is already in .trash folder
    # Normalize path separators to handle both forward and backward slashes
    norm_rel = rel.replace("/", os.sep).replace("\\", os.sep)
    is_in_trash = ".trash" in norm_rel.split(os.sep)
    
    # If explicitly requested permanent OR if it's already in trash, delete it forever
    permanent = bool(body.get("permanent", False)) or is_in_trash

    if not rel:
        return jsonify({"ok": False, "error": "Missing 'path'"}), 400

    try:
        target = _safe_under_base(base, rel)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    if not os.path.exists(target):
        return jsonify({"ok": False, "error": "Not found"}), 404

    # Extra guard: do not allow deleting the base itself
    if os.path.abspath(target) == base:
        return jsonify({"ok": False, "error": "Refusing to delete the root directory"}), 400

    try:
        if permanent:
            # PROTECTED FOLDERS LOGIC
            # Check if we are targeting a protected root folder
            # We normalized norm_rel earlier
            # If norm_rel has no separators, it is in the root
            is_root_item = (os.sep not in norm_rel)
            protected_folders = {".trash", "videos", "images"}
            
            if is_root_item and norm_rel in protected_folders:
                if norm_rel == ".trash":
                    # Special case: "Delete .trash" means "Empty .trash"
                    # Delete all contents but keep the folder
                    for item in os.listdir(target):
                        item_path = os.path.join(target, item)
                        try:
                            if os.path.isdir(item_path) and not os.path.islink(item_path):
                                shutil.rmtree(item_path)
                            else:
                                os.remove(item_path)
                        except Exception:
                            pass # best effort
                    action = "emptied_trash"
                else:
                    return jsonify({"ok": False, "error": f"Cannot delete protected folder '{rel}'"}), 403
            else:
                # Normal delete
                if os.path.isdir(target) and not os.path.islink(target):
                    shutil.rmtree(target)
                else:
                    os.remove(target)
                action = "deleted"
        else:
            trash_dir = os.path.join(base, ".trash")
            os.makedirs(trash_dir, exist_ok=True)
            name = os.path.basename(target.rstrip(os.sep)) or "item"
            uid = uuid.uuid4().hex[:8]
            root, ext = os.path.splitext(name)
            trash_name = f"{root}_{uid}{ext}" if ext else f"{name}_{uid}"
            dest = os.path.join(trash_dir, trash_name)
            shutil.move(target, dest)
            action = "moved_to_trash"

        free_pct = _read_disk_free_percent(config)
        _log(config, state, "INFO", f"delete_entry():Action:{action} path='{rel}'")
        return jsonify({
            "ok": True,
            "action": action,
            "path": rel,
            "disk_free_pct": None if free_pct is None else round(free_pct, 1)
        })
    except Exception as e:
        _log(config, state, "ERROR", f"delete_entry():Failed to delete file/directory: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
