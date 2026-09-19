#!/usr/bin/env python3
"""The prayer pages and the settings form, over the LAN at http://<hostname>.local

Runs as scheduler_web_ui.service. Python standard library only - there is nothing to pip
install on the device, and nothing to keep updated. Roughly 20 MB resident, and no CPU at
all while nobody has a page open: the countdown ticks in the browser and comes back only
at the instants the colour changes.

Serves no HTML of its own. The pages under site/ are plain files that fetch JSON, so the
same directory can be uploaded to a static host later - see tools/build_static_site.py.

No authentication, by choice: anyone on the LAN can change this device's settings, the
same as anyone standing in front of its touch screen. See ADMIN_MANUAL.md section 16.
"""

import argparse
import json
import os
import posixpath
import socket
import subprocess
import sys
import threading
import urllib.parse
import zipfile
from datetime import date as date_cls, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# applications/, so "from shared import ..." works however the service was started.
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from shared import mute as mute_lib, prayer_logic  # noqa: E402
import api  # noqa: E402

DEFAULT_PORT = 80
SITE_DIR = os.path.join(HERE, "site")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".ttf": "font/ttf",
    ".woff2": "font/woff2",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json; charset=utf-8",
}

# The pages, by the URL each is reached at. A fixed table rather than a path joined onto
# SITE_DIR: nothing a request can say is ever turned into a file name.
PAGES = {
    "/": "index.html",
    "/countdown/": "countdown/index.html",
    "/daily/": "daily/index.html",
    "/settings/": "settings/index.html",
}
# The assets those pages ask for, likewise fixed.
ASSETS = ("app.css", "app.js", "config.js", "manifest.webmanifest")

# Added to the home screen from a phone, the site should carry the same icon the touch
# screen does rather than a blank page glyph. Served from config/icons/ for the reason
# the font is served from the zip: they are already in every release payload, and a copy
# under site/ would be the same picture shipped twice and able to drift.
ICON_DIR = "config/icons"
ICONS = {
    "icon-32.png": "athan-app-icon-32.png",
    "icon-128.png": "athan-app-icon-128.png",
    "icon-256.png": "athan-app-icon-256.png",
}

# Amiri is what the touch screen draws in, and a phone on this LAN may have no route to
# the internet to fetch a webfont - so it is served from here. Read out of the zip the
# device already ships rather than committed a second time: 421 KB in every release
# payload, for a file that is already in it.
FONT_ZIP = "config/fonts/arabic-fonts/Amiri.zip"
FONT_MEMBER = "Amiri-Regular.ttf"
FONT_URL_NAME = "Amiri.ttf"

APPLY_TIMEOUT_SECONDS = 300


class Device:
    """Where this device keeps its things, and the one job that takes time."""

    def __init__(self, scheduler_dir, desktop_dir):
        self.scheduler_dir = scheduler_dir
        self.desktop_dir = desktop_dir
        self.ini_path = os.path.join(scheduler_dir, "config", "config.ini")
        self.map_path = os.path.join(scheduler_dir, "config", "prayer_times_map.py")
        self.apply_script = os.path.join(scheduler_dir, "config", "scripts",
                                         "apply_settings.sh")
        self.apply_log = os.path.join(scheduler_dir, "logs", "apply_settings.log")
        # One save at a time, and never while the touch screen is mid-save either: both
        # write config.ini and then run apply_settings.sh, and interleaving the two would
        # rebuild the prayer map from a half-written file.
        self.lock = threading.Lock()
        self.apply_state = {"state": "idle", "log": ""}
        self._font = None
        self._icons = {}

    def font(self):
        """Amiri-Regular, out of the zip, read once and kept."""
        if self._font is not None:
            return self._font or None
        path = os.path.join(self.scheduler_dir, FONT_ZIP)
        try:
            with zipfile.ZipFile(path) as bundle:
                self._font = bundle.read(FONT_MEMBER)
        except (OSError, KeyError, zipfile.BadZipFile):
            self._font = b""
        return self._font or None

    def icon(self, name):
        """One of ICONS, read once and kept. Same shape as font() above."""
        if name in self._icons:
            return self._icons[name] or None
        path = os.path.join(self.scheduler_dir, ICON_DIR, ICONS[name])
        try:
            with open(path, "rb") as handle:
                self._icons[name] = handle.read()
        except OSError:
            self._icons[name] = b""
        return self._icons[name] or None

    def reload_times(self):
        """The prayer map is rewritten under a running server - by apply_settings.sh here,
        from the Settings app, and by the new year's cron job - so it is re-read whenever
        it has changed rather than held from startup."""
        if prayer_logic.PRAYER_MAP_FILE != self.map_path:
            prayer_logic.PRAYER_MAP_FILE = self.map_path
            return prayer_logic.load_prayer_times()
        if prayer_logic.prayer_times_changed():
            return prayer_logic.load_prayer_times()
        return True

    def start_apply(self):
        """Run apply_settings.sh off the request thread, as the Settings app runs it off
        the UI thread. The page polls /api/apply rather than holding a connection open
        for the several seconds it takes, plus the scheduler restart."""
        if self.apply_state["state"] == "running":
            return
        self.apply_state = {"state": "running", "log": ""}
        threading.Thread(target=self._apply, daemon=True).start()

    def _apply(self):
        try:
            os.makedirs(os.path.dirname(self.apply_log), exist_ok=True)
            result = subprocess.run(["bash", self.apply_script], capture_output=True,
                                    text=True, timeout=APPLY_TIMEOUT_SECONDS)
            output = result.stdout + result.stderr
            with open(self.apply_log, "a", encoding="utf-8") as log:
                log.write(f"\n==== web {datetime.now():%Y-%m-%d %H:%M:%S} ====\n")
                log.write(output)
            state = "ok" if result.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            output = "apply_settings.sh did not finish."
            state = "failed"
        except OSError as error:
            output = f"Failed to run apply_settings.sh: {error}"
            state = "failed"
        self.apply_state = {"state": state, "log": tail(output)}


def tail(text, lines=40):
    return "\n".join(text.strip().splitlines()[-lines:])


def local_ip():
    """This device's address on the LAN, for a phone whose mDNS does not resolve .local.

    Asked of the routing table rather than of DNS: gethostbyname on a Pi answers 127.0.1.1
    from /etc/hosts. No packet is sent - a UDP socket only picks a route."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 1))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


class Handler(BaseHTTPRequestHandler):
    device = None
    server_version = "scheduler-web"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ---- plumbing ---------------------------------------------------------
    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Every answer is about this moment or about a file the touch screen may have
        # rewritten. Nothing here may be served from a browser cache.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status, message):
        self.send_json({"error": message}, status)

    def same_origin(self):
        """A POST must come from a page this device served.

        Without this, any site a phone on this LAN happens to open could post to
        http://<hostname>.local/api/settings in the background. There is no login to
        steal, but there is no reason to let a stranger's page restart the scheduler."""
        origin = self.headers.get("Origin")
        if origin is None:
            # A form posted by our own page always sends one. No Origin means something
            # that is not a browser, which is fine from the LAN - curl, a script.
            return self.headers.get("Sec-Fetch-Site") in (None, "same-origin")
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    # ---- routing ----------------------------------------------------------
    def do_GET(self):
        path, query = self.split_path()
        try:
            if path in PAGES:
                return self.serve_file(PAGES[path])
            # "/countdown" without the slash is what someone types.
            if path.rstrip("/") + "/" in PAGES and path != "/":
                return self.redirect(path.rstrip("/") + "/")
            if path.startswith("/static/"):
                return self.serve_asset(path[len("/static/"):])
            if path == "/api/day":
                return self.api_day(query)
            if path == "/api/settings":
                return self.api_settings_get()
            if path == "/api/mute":
                return self.api_mute_get()
            if path == "/api/apply":
                return self.send_json(self.device.apply_state)
            if path == "/api/device":
                return self.api_device()
            return self.fail(404, "not found")
        except Exception as error:  # a broken page must not take the service down
            self.log_message("error on %s: %s", path, error)
            return self.fail(500, str(error))

    def do_POST(self):
        path, _ = self.split_path()
        if not self.same_origin():
            return self.fail(403, "cross-origin request refused")
        try:
            if path == "/api/settings":
                return self.api_settings_post()
            if path == "/api/mute":
                return self.api_mute_post()
            return self.fail(404, "not found")
        except Exception as error:
            self.log_message("error on %s: %s", path, error)
            return self.fail(500, str(error))

    def split_path(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        if not path.startswith("/"):
            path = "/" + path
        return posixpath.normpath(path) + ("/" if path.endswith("/") and path != "/" else ""), \
            urllib.parse.parse_qs(parsed.query)

    def redirect(self, to):
        self.send_response(301)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ---- files ------------------------------------------------------------
    def serve_file(self, relative):
        full = os.path.join(SITE_DIR, relative)
        try:
            with open(full, "rb") as handle:
                body = handle.read()
        except OSError:
            return self.fail(404, "not found")
        suffix = os.path.splitext(full)[1]
        self.send_bytes(body, CONTENT_TYPES.get(suffix, "application/octet-stream"))

    def serve_asset(self, name):
        if name == FONT_URL_NAME:
            return self.serve_font()
        if name in ICONS:
            return self.serve_icon(name)
        if name not in ASSETS:
            return self.fail(404, "not found")
        self.serve_file(name)

    def serve_icon(self, name):
        body = self.device.icon(name)
        if body is None:
            # A missing icon is a page without one, not a page that fails to load.
            return self.fail(404, "icon not installed")
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[".png"])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def serve_font(self):
        body = self.device.font()
        if body is None:
            # The page names a fallback stack, so a missing font is a plainer screen
            # rather than a broken one.
            return self.fail(404, "font not installed")
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[".ttf"])
        self.send_header("Content-Length", str(len(body)))
        # The one thing here that never changes between requests.
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    # ---- api --------------------------------------------------------------
    def api_day(self, query):
        self.device.reload_times()
        raw = (query.get("date") or [None])[0]
        try:
            when = date_cls.fromisoformat(raw) if raw else datetime.now().date()
        except ValueError:
            return self.fail(400, "date must be YYYY-MM-DD")
        payload = api.day_payload(when)
        if payload is None:
            return self.fail(404, f"no prayer times for {when.isoformat()}")
        payload["now"] = datetime.now().isoformat(timespec="seconds")
        self.send_json(payload)

    def api_device(self):
        self.send_json({
            "hostname": socket.gethostname(),
            "ip": local_ip(),
            "now": datetime.now().isoformat(timespec="seconds"),
        })

    def api_settings_get(self):
        self.send_json(api.settings_payload(self.device.ini_path,
                                            self.device.scheduler_dir,
                                            self.device.desktop_dir))

    def api_settings_post(self):
        submitted = self.read_json()
        if submitted is None:
            return self.fail(400, "expected a JSON object")

        if not self.device.lock.acquire(blocking=False):
            return self.fail(409, "جارٍ حفظ إعدادات أخرى، حاول بعد قليل")
        try:
            api.apply_submission(self.device.ini_path, self.device.scheduler_dir,
                                 self.device.desktop_dir, submitted)
        except api.Invalid as refusal:
            return self.fail(400, str(refusal))
        finally:
            self.device.lock.release()

        self.device.start_apply()
        self.send_json({"saved": True})

    def api_mute_get(self):
        expiry = mute_lib.mute_expiry()
        sink = mute_lib.audio_is_muted()
        reason = mute_lib.last_error()
        if sink is None and reason:
            # Logged as well as sent: the page has room for one short line, and this is
            # the sentence that says which of wpctl, PipeWire or XDG_RUNTIME_DIR is at
            # fault. Without it "the speaker could not be reached" is a dead end.
            self.log_message("mute: %s (XDG_RUNTIME_DIR=%s)", reason,
                             os.environ.get("XDG_RUNTIME_DIR", "unset"))
        self.send_json({
            "muted": sink if sink is not None else mute_lib.is_muted(),
            "flag_until": (datetime.fromtimestamp(expiry).isoformat(timespec="seconds")
                           if expiry else None),
            "sink_reachable": sink is not None,
            "reason": reason if sink is None else "",
            "runtime_dir": os.environ.get("XDG_RUNTIME_DIR", ""),
            "minutes": mute_lib.MUTE_DURATION_MINUTES,
        })

    def api_mute_post(self):
        body = self.read_json() or {}
        want = body.get("muted")
        if want is None:
            want = not mute_lib.is_muted()
        want = bool(want)

        if want:
            mute_lib.write_mute_flag()
            # Only if the device cannot be silenced is the player killed instead. That
            # silences it just as fast but cannot be undone, so it is the last resort -
            # the same order the touch screen's own button uses.
            if not mute_lib.audio_set_mute(True):
                mute_lib.stop_current_audio()
        else:
            mute_lib.clear_mute_flag()
            mute_lib.audio_set_mute(False)

        self.api_mute_get()

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 1_000_000:
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


def build_server(scheduler_dir, desktop_dir, port, bind="0.0.0.0"):
    device = Device(scheduler_dir, desktop_dir)
    device.reload_times()

    handler = type("BoundHandler", (Handler,), {"device": device})
    server = ThreadingHTTPServer((bind, port), handler)
    server.daemon_threads = True
    return server, device


def main():
    home = os.path.expanduser("~")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--scheduler-dir",
                        default=os.path.join(home, "Desktop", "scheduler"))
    parser.add_argument("--desktop-dir", default=os.path.join(home, "Desktop"))
    args = parser.parse_args()

    server, _ = build_server(args.scheduler_dir, args.desktop_dir, args.port, args.bind)
    address = local_ip() or args.bind
    print(f"Prayer scheduler website on http://{socket.gethostname()}.local"
          f"{'' if args.port == 80 else ':' + str(args.port)}"
          f"  (http://{address}{'' if args.port == 80 else ':' + str(args.port)})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
