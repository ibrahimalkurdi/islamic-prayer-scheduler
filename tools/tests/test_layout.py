#!/usr/bin/env python3
"""Do the pages fit the phones they are opened on?

Measured in a real browser rather than judged from a screenshot. Two things are checked
at each size, and both have already gone wrong once:

  * nothing may be wider than the screen. The settings form overflowed at 360px, because
    an Arabic label and its number field sat on one line that could not fit.
  * the daily list has to show all seven prayers without scrolling. Two fell off a
    640px-tall phone, which is what the smallest common Android reports.

Skipped where there is no Chrome - this checks the front end, not anything that ships.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import date as date_cls, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VARIANT = "scheduler-official-touch-screen-with-raspberry-pi-4"
APPLICATIONS = os.path.join(REPO, VARIANT, "applications")
WEB_UI = os.path.join(APPLICATIONS, "services", "web_ui")
sys.path.insert(0, APPLICATIONS)
sys.path.insert(0, WEB_UI)

CHROME = next((c for c in ("google-chrome", "chromium", "chromium-browser")
               if shutil.which(c)), None)
if CHROME is None:
    print("SKIPPED - no Chrome on this machine")
    sys.exit(0)

FAILURES = []
CHECKS = 0


def check(label, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"  {label}\n    got  {got!r}\n    want {want!r}")


ROOT = tempfile.mkdtemp(prefix="layout-test-")
DESKTOP = os.path.join(ROOT, "Desktop")
SCHEDULER = os.path.join(DESKTOP, "scheduler")
for sub in ("config/fonts/arabic-fonts", "logs", "var", "audio/quran", "audio/duha"):
    os.makedirs(os.path.join(SCHEDULER, sub), exist_ok=True)
shutil.copy(os.path.join(REPO, VARIANT, "config", "fonts", "arabic-fonts", "Amiri.zip"),
            os.path.join(SCHEDULER, "config", "fonts", "arabic-fonts", "Amiri.zip"))

now = datetime.now()
ROWS = []
day = date_cls(now.year, 1, 1)
while day.year == now.year:
    ROWS.append({"Month": day.month, "Day": day.day, "Fajr": "04:46",
                 "Sunrise": "06:38", "Dhuhr": "13:06", "Asr": "16:28",
                 "Maghrib": "19:24", "Isha": "20:54"})
    day += timedelta(days=1)
with open(os.path.join(SCHEDULER, "config", "prayer_times_map.py"), "w",
          encoding="utf-8") as handle:
    handle.write("prayerTimes = " + repr(ROWS))
with open(os.path.join(SCHEDULER, "config", "config.ini"), "w", encoding="utf-8") as h:
    h.write("[Settings]\nduha_time = 60\ntahajjud_time = 20\n"
            "athkar_elsabah_time = 240\nathkar_elmasa_time = 20\n"
            "friday_quran_time = 60\nenable_duha_prayer = True\n"
            "enable_listen_to_quran = True\nlisten_to_quran = 06:30\n"
            "friday_quran_position = after\nquran_audio_checked = one.mp3\n")
for name in ("one.mp3", "two.mp3"):
    open(os.path.join(SCHEDULER, "audio", "quran", name), "w").close()
open(os.path.join(SCHEDULER, "audio", "duha", "duha.mp3"), "w").close()

os.environ["HOME"] = ROOT
import main as web  # noqa: E402

PROBE_HTML = """<!doctype html>
<meta charset="utf-8">
<body style="margin:0">
<iframe id="f" style="border:0"></iframe>
<script>
/* Frames the page under test at an exact size, waits for it to lay out, and writes what
   it measured into this document's title - which --dump-dom prints. Same origin as the
   page it frames, so it can read across into it without any security flags. */
const params = new URLSearchParams(location.search);
const frame = document.getElementById("f");
frame.style.width = params.get("w") + "px";
frame.style.height = params.get("h") + "px";
frame.src = "/" + (params.get("path") || "");
frame.addEventListener("load", () => setTimeout(() => {
    try {
        const d = frame.contentDocument;
        const rows = d.querySelectorAll(".row");
        document.title = JSON.stringify({
            scrollWidth: d.documentElement.scrollWidth,
            clientWidth: d.documentElement.clientWidth,
            rows: rows.length,
            lastRowBottom: rows.length
                ? Math.ceil(rows[rows.length - 1].getBoundingClientRect().bottom)
                : null,
        });
    } catch (error) {
        document.title = "ERR:" + error.message;
    }
}, 2000));
</script>
"""


class ProbeHandler(web.Handler):
    """The shipped handler plus one route, added here rather than in the service: a
    measuring page has no business being served by a device."""

    def do_GET(self):
        if self.path.split("?")[0] == "/probe.html":
            return self.send_bytes(PROBE_HTML.encode("utf-8"),
                                   "text/html; charset=utf-8")
        return super().do_GET()


server, _ = web.build_server(SCHEDULER, DESKTOP, 0, "127.0.0.1")
server.RequestHandlerClass = type("BoundProbe", (ProbeHandler,),
                                  {"device": server.RequestHandlerClass.device})
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"

PROFILE = os.path.join(ROOT, "chrome")

# The phones this actually has to work on. 360x640 is the smallest Android still in the
# field; 412x732 is what a current handset reports once the browser's own chrome is taken
# out of the window.
SIZES = [("360x640", 360, 640), ("412x732", 412, 732), ("1440x820", 1440, 820)]

PAGES = ["", "countdown/", "daily/", "settings/"]


def probe(path, width, height):
    """What the page measures about itself at that size, or None if it could not say."""
    url = f"{BASE}/probe.html?path={path}&w={width}&h={height}"
    result = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--user-data-dir={PROFILE}", f"--window-size={width + 60},{height + 140}",
         "--virtual-time-budget=8000", "--dump-dom", url],
        capture_output=True, text=True, timeout=120)
    start = result.stdout.find("<title>")
    end = result.stdout.find("</title>")
    if start == -1 or end == -1:
        return None
    text = result.stdout[start + 7:end].replace("&quot;", '"')
    try:
        return json.loads(text)
    except ValueError:
        FAILURES.append(f"  probing /{path} at {width}x{height}: {text}")
        return None


print("1. nothing is wider than the screen it is on")
for label, width, height in SIZES:
    for page in PAGES:
        found = probe(page, width, height)
        if found is None:
            FAILURES.append(f"  could not measure /{page} at {label}")
            continue
        name = page or "(home)"
        check(f"/{name} at {label} does not scroll sideways",
              found["scrollWidth"] <= found["clientWidth"], True)

print("2. the whole day fits a short phone without scrolling")
for label, width, height in (("360x640", 360, 640), ("390x664", 390, 664),
                             ("412x732", 412, 732)):
    found = probe("daily/", width, height)
    if found is None:
        FAILURES.append(f"  could not measure the daily list at {label}")
        continue
    check(f"all seven prayers are in the list at {label}", found["rows"], 7)
    check(f"and the last one ends inside the screen at {label}",
          found["lastRowBottom"] is not None and found["lastRowBottom"] <= height, True)

server.shutdown()
shutil.rmtree(ROOT, ignore_errors=True)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)} of {CHECKS} checks)")
    print("\n".join(FAILURES))
    sys.exit(1)
print(f"ALL PASS ({CHECKS} checks)")
