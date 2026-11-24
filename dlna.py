"""Minimal DLNA/UPnP client: SSDP discovery + AVTransport/RenderingControl SOAP."""
import re
import socket
import time
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from xml.sax.saxutils import escape

SSDP_ADDR = ("239.255.255.250", 1900)
AVT = "urn:schemas-upnp-org:service:AVTransport:1"
RC = "urn:schemas-upnp-org:service:RenderingControl:1"


def local_ip_for(target_host="8.8.8.8"):
    """IP of the local interface that routes to target_host (the TV's LAN)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target_host, 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _http(url, data=None, headers=None, timeout=5):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _ns(tag):
    return tag.split("}", 1)[-1]


def describe(location):
    """Fetch a device description; return dict or None if not a usable renderer."""
    try:
        root = ET.fromstring(_http(location, timeout=4))
    except Exception:
        return None
    dev = None
    for el in root.iter():
        if _ns(el.tag) == "device":
            dev = el
            break
    if dev is None:
        return None
    info = {"location": location, "name": None, "av": None, "rc": None}
    for child in dev:
        if _ns(child.tag) == "friendlyName":
            info["name"] = child.text
    for svc in root.iter():
        if _ns(svc.tag) != "service":
            continue
        d = {_ns(c.tag): (c.text or "") for c in svc}
        url = urljoin(location, d.get("controlURL", ""))
        if d.get("serviceType", "").startswith("urn:schemas-upnp-org:service:AVTransport"):
            info["av"] = url
        elif d.get("serviceType", "").startswith("urn:schemas-upnp-org:service:RenderingControl"):
            info["rc"] = url
    if not info["av"]:
        return None
    info["name"] = info["name"] or urlparse(location).hostname
    info["ip"] = urlparse(location).hostname
    info["id"] = info["ip"]
    return info


def discover(timeout=3):
    """SSDP M-SEARCH for media renderers. Returns list of device dicts."""
    msg = "\r\n".join([
        "M-SEARCH * HTTP/1.1",
        "HOST: 239.255.255.250:1900",
        'MAN: "ssdp:discover"',
        "MX: 2",
        "ST: urn:schemas-upnp-org:device:MediaRenderer:1",
        "", ""]).encode()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    sock.settimeout(0.5)
    locations = set()
    try:
        for _ in range(2):
            sock.sendto(msg, SSDP_ADDR)
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, _ = sock.recvfrom(65507)
            except socket.timeout:
                continue
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m:
                locations.add(m.group(1).decode())
    finally:
        sock.close()
    devices = {}
    for loc in locations:
        d = describe(loc)
        if d:
            devices[d["id"]] = d
    return list(devices.values())


def _soap(url, service, action, args):
    body = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in args.items())
    env = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{service}">{body}</u:{action}></s:Body></s:Envelope>'
    ).encode()
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"{service}#{action}"',
    }
    try:
        out = _http(url, env, headers, timeout=8)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{action} failed: HTTP {e.code} {e.read()[:200]!r}")
    res = {}
    try:
        for el in ET.fromstring(out).iter():
            if el.text and el.text.strip() and len(el) == 0:
                res[_ns(el.tag)] = el.text
    except ET.ParseError:
        pass
    return res


def _didl(url, title, mime):
    pi = f"http-get:*:{mime}:DLNA.ORG_OP=01;DLNA.ORG_FLAGS=01700000000000000000000000000000"
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
        '<item id="0" parentID="-1" restricted="1">'
        f"<dc:title>{escape(title)}</dc:title>"
        "<upnp:class>object.item.videoItem</upnp:class>"
        f'<res protocolInfo="{pi}">{escape(url)}</res>'
        "</item></DIDL-Lite>"
    )


class Renderer:
    def __init__(self, info):
        self.av, self.rc = info["av"], info.get("rc")

    def play_url(self, url, title="Video", mime="video/mp4"):
        try:
            _soap(self.av, AVT, "Stop", {"InstanceID": 0})
        except Exception:
            pass
        _soap(self.av, AVT, "SetAVTransportURI", {
            "InstanceID": 0, "CurrentURI": url,
            "CurrentURIMetaData": _didl(url, title, mime)})
        _soap(self.av, AVT, "Play", {"InstanceID": 0, "Speed": 1})

    def play(self):
        _soap(self.av, AVT, "Play", {"InstanceID": 0, "Speed": 1})

    def pause(self):
        _soap(self.av, AVT, "Pause", {"InstanceID": 0})

    def stop(self):
        _soap(self.av, AVT, "Stop", {"InstanceID": 0})

    def seek(self, seconds):
        seconds = max(0, int(seconds))
        t = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        _soap(self.av, AVT, "Seek", {"InstanceID": 0, "Unit": "REL_TIME", "Target": t})

    def set_volume(self, vol):
        if self.rc:
            _soap(self.rc, RC, "SetVolume", {
                "InstanceID": 0, "Channel": "Master", "DesiredVolume": int(vol)})

    def status(self):
        st = _soap(self.av, AVT, "GetTransportInfo", {"InstanceID": 0})
        pos = _soap(self.av, AVT, "GetPositionInfo", {"InstanceID": 0})
        out = {
            "state": st.get("CurrentTransportState", "UNKNOWN"),
            "position": _secs(pos.get("RelTime")),
            "duration": _secs(pos.get("TrackDuration")),
        }
        if self.rc:
            try:
                v = _soap(self.rc, RC, "GetVolume", {"InstanceID": 0, "Channel": "Master"})
                out["volume"] = int(v.get("CurrentVolume", 0))
            except Exception:
                pass
        return out


def _secs(s):
    if not s or not re.match(r"^\d+:\d+:\d+", s):
        return 0
    h, m, sec = s.split(".")[0].split(":")
    return int(h) * 3600 + int(m) * 60 + int(sec)
