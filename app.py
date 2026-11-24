"""Cast videos to a DLNA/UPnP TV on your local network from any phone browser.

Run:  python app.py   then open http://<this-computer-ip>:5000 on your phone.
"""
import mimetypes
import os
from pathlib import Path
from urllib.parse import quote, urlparse

from flask import Flask, abort, jsonify, render_template, request, send_from_directory
from werkzeug.utils import secure_filename

import dlna

BASE = Path(__file__).parent
MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", BASE / "media")).resolve()
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("PORT", 5000))
VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".ts", ".wmv", ".mpg", ".mpeg"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = None  # allow large video uploads
devices = {}  # id -> info


def _mime(name):
    m = mimetypes.guess_type(name)[0]
    if name.lower().endswith(".mkv"):
        m = "video/x-matroska"
    return m or "video/mp4"


def _renderer(dev_id):
    info = devices.get(dev_id)
    if not info:
        abort(404, "Unknown device — rescan")
    return info, dlna.Renderer(info)


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/devices")
def api_devices():
    if request.args.get("scan") or not devices:
        for d in dlna.discover():
            devices[d["id"]] = d
    return jsonify([{"id": d["id"], "name": d["name"], "ip": d["ip"]} for d in devices.values()])


@app.post("/api/devices/add")
def api_add_device():
    """Manual fallback when SSDP is blocked: give TV IP or description URL."""
    target = (request.json or {}).get("target", "").strip()
    if not target:
        abort(400)
    urls = [target] if target.startswith("http") else []
    d = None
    for u in urls:
        d = dlna.describe(u)
    if not d:
        return jsonify(error="Could not read device. Paste the full description URL "
                             "(http://TV_IP:PORT/…xml)."), 400
    devices[d["id"]] = d
    return jsonify(id=d["id"], name=d["name"], ip=d["ip"])


@app.get("/api/library")
def api_library():
    files = sorted(
        (p for p in MEDIA_DIR.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXT),
        key=lambda p: p.stat().st_mtime, reverse=True)
    return jsonify([{"path": p.relative_to(MEDIA_DIR).as_posix(),
                     "name": p.name, "size": p.stat().st_size} for p in files])


@app.post("/api/upload")
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        abort(400)
    name = secure_filename(f.filename)
    if Path(name).suffix.lower() not in VIDEO_EXT:
        return jsonify(error="Not a supported video file"), 400
    f.save(MEDIA_DIR / name)
    return jsonify(path=name, name=name)


@app.get("/media/<path:rel>")
def media(rel):
    # conditional=True gives HTTP Range support, which TVs need for seeking.
    resp = send_from_directory(MEDIA_DIR, rel, conditional=True, mimetype=_mime(rel))
    resp.headers["transferMode.dlna.org"] = "Streaming"
    resp.headers["contentFeatures.dlna.org"] = (
        "DLNA.ORG_OP=01;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
    return resp


@app.post("/api/cast")
def api_cast():
    data = request.json or {}
    info, r = _renderer(data.get("device"))
    if data.get("url"):  # remote URL: the TV fetches it directly
        url = data["url"]
        title = Path(urlparse(url).path).name or "Video"
        mime = _mime(title)
    elif data.get("path"):
        p = (MEDIA_DIR / data["path"]).resolve()
        if MEDIA_DIR not in p.parents or not p.is_file():
            abort(404)
        host = dlna.local_ip_for(info["ip"])
        url = f"http://{host}:{PORT}/media/{quote(data['path'])}"
        title, mime = p.name, _mime(p.name)
    else:
        abort(400)
    try:
        r.play_url(url, title, mime)
    except Exception as e:
        return jsonify(error=str(e)), 502
    return jsonify(ok=True, url=url)


@app.post("/api/control")
def api_control():
    data = request.json or {}
    _, r = _renderer(data.get("device"))
    act = data.get("action")
    try:
        if act == "play": r.play()
        elif act == "pause": r.pause()
        elif act == "stop": r.stop()
        elif act == "seek": r.seek(data["value"])
        elif act == "volume": r.set_volume(data["value"])
        else: abort(400)
    except RuntimeError as e:
        return jsonify(error=str(e)), 502
    return jsonify(ok=True)


@app.get("/api/status/<dev_id>")
def api_status(dev_id):
    _, r = _renderer(dev_id)
    try:
        return jsonify(r.status())
    except Exception as e:
        return jsonify(error=str(e)), 502


if __name__ == "__main__":
    ip = dlna.local_ip_for()
    print(f"\n  Open on your phone:  http://{ip}:{PORT}\n  Media folder: {MEDIA_DIR}\n")
    app.run(host="0.0.0.0", port=PORT, threaded=True)
