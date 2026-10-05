#!/usr/bin/env python3
"""The website, against a fixture device tree. No network, no real Raspberry Pi.

Starts the real server on a high port with a fake scheduler directory under it, then
drives it the way a browser does. The mute calls reach a `wpctl` that is a shell script
on PATH, so the fallback paths are exercised without a sound card.
"""

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date as date_cls, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VARIANT = "scheduler-official-touch-screen-with-raspberry-pi-4"
APPLICATIONS = os.path.join(REPO, VARIANT, "applications")
WEB_UI = os.path.join(APPLICATIONS, "services", "web_ui")
sys.path.insert(0, APPLICATIONS)
sys.path.insert(0, WEB_UI)

FAILURES = []
CHECKS = 0


def check(label, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"  {label}\n    got  {got!r}\n    want {want!r}")


def check_true(label, got):
    check(label, bool(got), True)


# ---------------------------------------------------------------------------
# A device tree
# ---------------------------------------------------------------------------
ROOT = tempfile.mkdtemp(prefix="web-ui-test-")
DESKTOP = os.path.join(ROOT, "Desktop")
SCHEDULER = os.path.join(DESKTOP, "scheduler")
for sub in ("config/scripts", "config/prayers-config", "config/fonts/arabic-fonts",
            "config/icons",
            "logs", "var", "audio/quran", "audio/fajr", "audio/duha",
            "audio/tahajjud", "audio/athkar_elsabah", "audio/athkar_elmasa",
            "audio/friday_quran", "audio/shorooq", "audio/dhuhr", "audio/asr",
            "audio/maghrib", "audio/isha"):
    os.makedirs(os.path.join(SCHEDULER, sub), exist_ok=True)

# The real icons, not stand-ins: the server reads them out of config/icons/ rather than
# from site/, so a fixture that invented its own would prove the route and not the file.
for icon in ("athan-app-icon-32.png", "athan-app-icon-128.png", "athan-app-icon-256.png"):
    shutil.copyfile(os.path.join(REPO, VARIANT, "config", "icons", icon),
                    os.path.join(SCHEDULER, "config", "icons", icon))
shutil.copyfile(os.path.join(REPO, VARIANT, "config", "fonts", "arabic-fonts", "Amiri.zip"),
                os.path.join(SCHEDULER, "config", "fonts", "arabic-fonts", "Amiri.zip"))

ROWS = []
day = date_cls(datetime.now().year, 1, 1)
while day.year == datetime.now().year:
    ROWS.append({"Month": day.month, "Day": day.day, "Fajr": "05:00",
                 "Sunrise": "06:00", "Dhuhr": "12:00", "Asr": "15:00",
                 "Maghrib": "18:00", "Isha": "20:00"})
    day += timedelta(days=1)

with open(os.path.join(SCHEDULER, "config", "prayer_times_map.py"), "w",
          encoding="utf-8") as handle:
    handle.write("prayerTimes = " + repr(ROWS))

CSV_PATH = os.path.join(DESKTOP, "إدخال-مواقيت-الصلاة-للمستخدم.csv")
with open(CSV_PATH, "w", encoding="utf-8") as handle:
    handle.write("Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha\n")
    for row in ROWS:
        handle.write(f"{row['Month']},{row['Day']},05:00,06:00,12:00,15:00,18:00,20:00\n")

INI = os.path.join(SCHEDULER, "config", "config.ini")
with open(INI, "w", encoding="utf-8") as handle:
    handle.write("""[Settings]
tahajjud_time = 20
duha_time = 60
athkar_elsabah_time = 240
athkar_elmasa_time = 20
friday_quran_time = 60
enable_tahajjud_prayer = True
enable_duha_prayer = True
enable_listen_to_quran = True
enable_friday_quran = True
enable_athkar_elsabah = True
enable_athkar_elmasa = True
enable_prayer_fajr = True
enable_prayer_sunrise = True
enable_prayer_dhuhr = True
enable_prayer_asr = True
enable_prayer_maghrib = True
enable_prayer_isha = True
listen_to_quran = 06:30
friday_quran_position = after
quran_audio_checked = one.mp3
""")

for name in ("one.mp3", "two.mp3"):
    open(os.path.join(SCHEDULER, "audio", "quran", name), "w").close()
open(os.path.join(SCHEDULER, "audio", "fajr", "athan.mp3"), "w").close()

# apply_settings.sh, stubbed: the real one rebuilds the prayer map and restarts a
# service, neither of which belongs in a test. It records that it ran.
APPLY_MARKER = os.path.join(ROOT, "applied")
APPLY = os.path.join(SCHEDULER, "config", "scripts", "apply_settings.sh")
with open(APPLY, "w", encoding="utf-8") as handle:
    handle.write(f'#!/bin/bash\necho "applied settings"\ndate >> "{APPLY_MARKER}"\n'
                 f'echo "${{TZ:-}}" >> "{ROOT}/applied-tz"\n')
os.chmod(APPLY, 0o755)

# What the Settings app also offers: the daylight-saving zone table and the shipped
# defaults are the real files; the city presets are the fixture's own times, so choosing
# one leaves every later check reading the same day; bad.csv is a file in no known format.
shutil.copyfile(os.path.join(REPO, VARIANT, "config", "scripts", "timezones_ar.py"),
                os.path.join(SCHEDULER, "config", "scripts", "timezones_ar.py"))
shutil.copyfile(os.path.join(REPO, VARIANT, "config", "default-config.ini"),
                os.path.join(SCHEDULER, "config", "default-config.ini"))
PRESETS = os.path.join(SCHEDULER, "config", "prayers-config")
for name in ("برلين.csv", "آخن.csv"):
    shutil.copyfile(CSV_PATH, os.path.join(PRESETS, name))
with open(os.path.join(PRESETS, "bad.csv"), "w", encoding="utf-8") as handle:
    handle.write("not,a,prayer,table\n")
# Damascus's own times, told apart from Berlin's by its Dhuhr.
DAMASCUS_CSV = open(CSV_PATH, encoding="utf-8").read().replace(",12:00,", ",12:30,")
with open(os.path.join(PRESETS, "دمشق.csv"), "w", encoding="utf-8") as handle:
    handle.write(DAMASCUS_CSV)
# The real zones.ini, so the test reads what ships.
shutil.copyfile(os.path.join(REPO, VARIANT, "config", "prayers-config", "zones.ini"),
                os.path.join(PRESETS, "zones.ini"))

# The jobs the website hands to the user's systemd, stubbed: systemd-run starts the
# command in the background and keeps its pid under the unit's name, which is what the
# stub systemctl answers is-active from. A file named "no-user-systemd" makes it fail,
# as it does on a device with nobody logged in.
UNITS = os.path.join(ROOT, "units")
os.makedirs(UNITS)
for name, text in (("systemd-run", f"""#!/bin/bash
[[ -f "{ROOT}/no-user-systemd" ]] && {{ echo "Failed to connect to bus" >&2; exit 1; }}
unit=""; envs=()
while [[ "$1" != "--" ]]; do
    case "$1" in
        --unit=*) unit="${{1#--unit=}}" ;;
        --setenv=*) envs+=("${{1#--setenv=}}") ;;
    esac
    shift
done
shift
echo "${{envs[*]}} | $*" >> "{UNITS}/$unit.calls"
env "${{envs[@]}}" "$@" > /dev/null 2>&1 &
echo $! > "{UNITS}/$unit.pid"
"""), ("systemctl", f"""#!/bin/bash
unit="${{@: -1}}"
pid="$(cat "{UNITS}/$unit.pid" 2>/dev/null)"
[[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
""")):
    with open(os.path.join(ROOT, "bin-jobs-" + name), "w", encoding="utf-8") as handle:
        handle.write(text)

# check_updates.sh, stubbed: --status reads a JSON file the test writes, --list and
# --latest answer from fixed versions, and anything else records its arguments, takes a
# moment as a real run does, and leaves the result in the status file.
UPDATE_STATUS = os.path.join(ROOT, "update-status.json")
with open(UPDATE_STATUS, "w", encoding="utf-8") as handle:
    json.dump({"installed": "1.5.5", "enabled": True, "pinned": "", "rollback_to": "1.5.4",
               "pointer": "VERSIONS.json", "pointer_is_default": True,
               "last_result": "up_to_date", "last_checked": "2026-10-04T02:00:00"}, handle)
CHECK_UPDATES = os.path.join(SCHEDULER, "config", "scripts", "check_updates.sh")
with open(CHECK_UPDATES, "w", encoding="utf-8") as handle:
    handle.write(f"""#!/bin/bash
case "$*" in
    --status)
        # ENABLED and PIN are update.conf's, as the real --status reports them.
        python3 - "{UPDATE_STATUS}" "$(dirname "$0")/../update.conf" <<'PY'
import json, re, sys
state = json.load(open(sys.argv[1]))
conf = open(sys.argv[2]).read()
enabled = re.search(r"^ENABLED=(.*)$", conf, re.M)
pin = re.search(r"^PIN=(.*)$", conf, re.M)
state["enabled"] = (enabled.group(1) if enabled else "true").lower() == "true"
state["pinned"] = pin.group(1) if pin else ""
print(json.dumps(state))
PY
        exit 0 ;;
    --list) printf '1.5.3\\n1.5.6\\n1.5.4\\n1.5.5\\n'; exit 0 ;;
    --latest) echo 1.5.6; exit 0 ;;
esac
echo "$*" >> "{ROOT}/update-ran"
sleep 1
python3 - "{UPDATE_STATUS}" <<'PY'
import json, sys, datetime
state = json.load(open(sys.argv[1]))
state["last_result"] = "updated"
state["last_checked"] = datetime.datetime.now().isoformat(timespec="seconds")
json.dump(state, open(sys.argv[1], "w"))
PY
""")
os.chmod(CHECK_UPDATES, 0o755)
with open(os.path.join(SCHEDULER, "config", "crontab.txt"), "w", encoding="utf-8") as handle:
    handle.write("00 02 * * * bash $HOME/Desktop/scheduler/config/scripts/check_updates.sh --cron\n")
with open(os.path.join(SCHEDULER, "config", "update.conf"), "w", encoding="utf-8") as handle:
    handle.write("ENABLED=true\nPIN=\n")

# init.sh, stubbed: a reset runs it, and it records whether it was told to skip its
# update check.
with open(os.path.join(SCHEDULER, "config", "scripts", "init.sh"), "w",
          encoding="utf-8") as handle:
    handle.write(f'#!/bin/bash\nsleep 1\necho "${{SCHEDULER_INIT_NO_UPDATE_CHECK:-}}${{SCHEDULER_INIT_APPLY_SETTINGS:-}}" >> "{ROOT}/init-ran"\n')

# wpctl, stubbed. Its mute state lives in a file so the server's reads and writes of it
# are really round-tripping through a subprocess, as they do on the device.
BIN = os.path.join(ROOT, "bin")
os.makedirs(BIN)
SINK_STATE = os.path.join(ROOT, "sink-muted")
WPCTL = os.path.join(BIN, "wpctl")
with open(WPCTL, "w", encoding="utf-8") as handle:
    handle.write(f"""#!/bin/bash
if [[ "$1" == "set-mute" ]]; then
    echo "$3" > "{SINK_STATE}"
    exit 0
fi
if [[ "$1" == "get-volume" ]]; then
    if [[ "$(cat "{SINK_STATE}" 2>/dev/null)" == "1" ]]; then
        echo "Volume: 0.50 [MUTED]"
    else
        echo "Volume: 0.50"
    fi
    exit 0
fi
exit 1
""")
os.chmod(WPCTL, 0o755)
# No live crontab, so the daily check's time is read from config/crontab.txt.
with open(os.path.join(BIN, "crontab"), "w", encoding="utf-8") as handle:
    handle.write("#!/bin/bash\nexit 1\n")
os.chmod(os.path.join(BIN, "crontab"), 0o755)
# The clock's zone, read from a file timedatectl reports, and sudo recording what the
# root helper would be asked to do.
OS_ZONE = os.path.join(ROOT, "os-zone")
with open(OS_ZONE, "w", encoding="utf-8") as handle:
    handle.write("Europe/Berlin\n")
with open(os.path.join(BIN, "timedatectl"), "w", encoding="utf-8") as handle:
    handle.write(f'#!/bin/bash\n[[ "$1" == show ]] && cat "{OS_ZONE}"\n')
with open(os.path.join(BIN, "sudo"), "w", encoding="utf-8") as handle:
    handle.write(f'#!/bin/bash\necho "$*" >> "{ROOT}/sudo-calls"\n'
                 f'[[ -f "{ROOT}/sudo-fails" ]] && {{ echo "unknown time zone" >&2; exit 2; }}\n'
                 'exit 0\n')
for name in ("timedatectl", "sudo"):
    os.chmod(os.path.join(BIN, name), 0o755)
for name in ("systemd-run", "systemctl"):
    shutil.move(os.path.join(ROOT, "bin-jobs-" + name), os.path.join(BIN, name))
    os.chmod(os.path.join(BIN, name), 0o755)
os.environ["PATH"] = BIN + os.pathsep + os.environ["PATH"]

# shared.mute resolves its paths from $HOME at import time, so $HOME is the fixture.
os.environ["HOME"] = ROOT

import main as web  # noqa: E402
import api  # noqa: E402
from shared import mute as mute_lib  # noqa: E402

server, device = web.build_server(SCHEDULER, DESKTOP, 0, "127.0.0.1")
PORT = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{PORT}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is part of what is being tested, so it must not be followed away."""
    def redirect_request(self, *args, **kwargs):
        return None


NO_REDIRECT = urllib.request.build_opener(NoRedirect)


def get(path, follow=True):
    request = urllib.request.Request(BASE + path)
    opener = urllib.request.urlopen if follow else NO_REDIRECT.open
    try:
        with opener(request, timeout=10) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def post(path, payload, origin=None, want_status=200):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(BASE + path, data=body, headers=headers,
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


print("1. the pages are served, and they are files not rendered HTML")
for path, needle in (("/", 'id="rows"'),
                     ("/countdown/", "id=\"digits\""),
                     ("/settings/", "الاعدادات")):
    status, body, headers = get(path)
    check(f"GET {path}", status, 200)
    check_true(f"{path} contains {needle}", needle in body.decode("utf-8"))
    check(f"{path} is html", headers["Content-Type"], "text/html; charset=utf-8")

print("2. the daily list is the landing page, and its icons are the way to the others")
_, body, _ = get("/")
home = body.decode("utf-8")
# Relative, so the same page works at / on the device and at /d/<name>/ on the public
# site, where the handed-out app lives.
for target in ("countdown/", "settings/"):
    check_true(f"the landing page links to {target}", f'href="{target}"' in home)
check_true("the settings icon starts hidden", 'class="icon-link hidden" id="to-settings"' in home)
check_true("and is shown on the device or in a device's app",
           'if (window.DEVICE || owner) document.querySelector("#to-settings")' in home)
check("there is no separate home page any more",
      os.path.exists(os.path.join(WEB_UI, "site", "index.html")), False)
for old in ("/daily/", "/daily"):
    status, _, headers = get(old, follow=False)
    check(f"GET {old} redirects", status, 301)
    check(f"{old} lands on the daily list at /", headers["Location"], "/")
countdown = get("/countdown/")[1].decode("utf-8")
check_true("the countdown goes back to the daily list, relative",
           'class="corner back-corner" href="../"' in countdown)
check_true("the settings page prints the address, for a phone that cannot resolve .local",
           'id="where"' in get("/settings/")[1].decode("utf-8"))
check_true("the settings page goes back to it, relative",
           'href="../">→ اوقات الصلاة' in get("/settings/")[1].decode("utf-8"))

print("3. a typed address without the trailing slash still lands")
status, _, headers = get("/countdown", follow=False)
check("GET /countdown redirects", status, 301)
check("to /countdown/", headers["Location"], "/countdown/")

print("4. the assets, and nothing else, are reachable")
for name, ctype in (("app.css", "text/css; charset=utf-8"),
                    ("app.js", "application/javascript; charset=utf-8"),
                    ("config.js", "application/javascript; charset=utf-8"),
                    ("manifest.webmanifest",
                     "application/manifest+json; charset=utf-8")):
    status, _, headers = get(f"/static/{name}")
    check(f"GET /static/{name}", status, 200)
    check(f"{name} content type", headers["Content-Type"], ctype)

# Added to a phone's home screen the site should carry the app's own icon rather than a
# blank glyph, which means the icon has to be reachable and has to be a real PNG - a 404
# body served as image/png would satisfy a status check and still show nothing.
for name in ("icon-32.png", "icon-128.png", "icon-256.png"):
    status, body, headers = get(f"/static/{name}")
    check(f"GET /static/{name}", status, 200)
    check(f"{name} content type", headers["Content-Type"], "image/png")
    check(f"{name} is really a PNG", body[:8], b"\x89PNG\r\n\x1a\n")

# Every face app.css names, served out of Amiri.zip as a real TrueType file. The bold one
# is what the counter and the running row's time are drawn in; without it the browser
# fakes a bold from the regular face.
css_fonts = re.findall(r'url\("/static/([^"]+\.ttf)"\)', get("/static/app.css")[1].decode())
check("app.css names the regular and the bold face", sorted(css_fonts),
      ["Amiri-Bold.ttf", "Amiri.ttf"])
for name in css_fonts:
    status, body, headers = get(f"/static/{name}")
    check(f"GET /static/{name}", status, 200)
    check(f"{name} is really TrueType", body[:4], b"\x00\x01\x00\x00")
check("the two faces are different files",
      get("/static/Amiri.ttf")[1] != get("/static/Amiri-Bold.ttf")[1], True)

# Every page, not just the home page: whichever one is open is the one that gets added.
for page in ("/", "/countdown/", "/settings/"):
    html = get(page)[1].decode("utf-8")
    check(f"{page} names an apple-touch-icon", 'rel="apple-touch-icon"' in html, True)
    check(f"{page} names a manifest", 'rel="manifest"' in html, True)

# The save button is at the foot of a long form and the result appears above it, so
# without this a tap on a phone answers somewhere off the top of the screen and reads as
# nothing having happened.
settings_html = get("/settings/")[1].decode("utf-8")
check_true("the settings page scrolls its result into view",
           "scrollIntoView" in settings_html)
check_true("and does not animate it for a reader who asked not to",
           "prefers-reduced-motion" in settings_html)

# Applying takes several seconds - the prayer map is rebuilt and the athan service
# restarted - so the page has to say it is working, and then has to stop saying it.
check_true("it covers the page while applying", 'id="working"' in settings_html)
check_true("with something that reads as working",
           'class="spinner"' in settings_html)
# Every path that leaves the applying state must take the cover down. One that does not
# leaves a spinner over a page nobody can touch, which is worse than no cover at all.
# Five for the save: a poll that fails, the apply finishing, a save refused, a no to
# the question about a time that does not fit every day, and a no to replacing a
# hand-edited prayer file picked but not yet chosen. Three for choosing a prayer
# file (no, done, failed), two for the reset (done, failed), three for an update (no,
# failed, finished), two for the daily-check switch (done, failed), three for an
# audio upload (no to replacing, done, failed), two for deleting files (done, failed)
# and two for the clock's zone (back, failed).
check("every exit from applying lowers the cover",
      settings_html.count("working(false)"), 22)
check_true("and the cover is raised on the tap", "working(true)" in settings_html)
# A file picked in the list and then saved with the main button was dropped: the save
# sent the settings alone, so the device stayed on the file it had while the list showed
# the new one.
save_handler = settings_html.split('document.querySelector("#save").addEventListener', 1)[1]
save_handler = save_handler.split("const Updates", 1)[0]
check_true("the save chooses a picked prayer file first",
           save_handler.index('"/api/prayer-source"') < save_handler.index('"/api/settings", {'))
check_true("only when it differs from the file in use",
           'picked.value !== source.chosen' in save_handler)
check_true("and waits for its rebuild before saving the rest",
           save_handler.index("waitForApply()") < save_handler.index('"/api/settings", {'))
# The overlay replaced an inline note; leaving the id behind in show()'s list would make
# it throw on a page that no longer has that element.
check("the busy note it replaced is gone", 'id="busy"' in settings_html, False)

spinner_css = get("/static/app.css")[1].decode("utf-8")
check_true("the spinner is defined", ".spinner" in spinner_css)
check_true("and stops spinning for reduced motion",
           "prefers-reduced-motion" in spinner_css)

manifest = json.loads(get("/static/manifest.webmanifest")[1])
# Resolved against the manifest's own URL, so a bare name here means /static/<name> on
# the device and static/<name> on a static host - one spelling that works in both.
for icon in manifest["icons"]:
    check(f"manifest icon {icon['src']} is relative", icon["src"].startswith("/"), False)
    check(f"manifest icon {icon['src']} is served",
          get(f"/static/{icon['src']}")[0], 200)

print("5. a path cannot be turned into a file name")
for attack in ("/static/../api.py", "/static/../../shared/mute.py",
               "/static/%2e%2e%2fapi.py", "/static/../../../../etc/passwd",
               "/api.py", "/site/app.css"):
    status, _, _ = get(attack, follow=False)
    check(f"{attack} is refused", status in (301, 404), True)

print("6. the day payload carries boundaries, not rules")
status, body, _ = get("/api/day")
check("GET /api/day", status, 200)
day_payload = json.loads(body)
check("seven periods", len(day_payload["periods"]), 7)
check_true("the badge palette is sent too",
           "badge" in day_payload["cards"] and "green" in day_payload["cards"]["badge"])
check_true("every period has spans",
           all(p["spans"] for p in day_payload["periods"] if p["start"] and p["end"]))
check_true("colours are sent, not assumed", "green" in day_payload["colors"])
check_true("the makrooh wording is sent", bool(day_payload["makrooh_notice"]))
names = [p["name"] for p in day_payload["periods"]]
check("in the order the screen lists them", names,
      ["الفجر", "الشروق", "الضحى", "الظهر", "العصر", "المغرب", "العشاء"])

print("7. the spans agree with the rules, at every second of the day")
# The same guarantee test_prayer_logic makes in Python, but over the wire, so a bug in
# the serialising is caught too.
from shared import prayer_logic  # noqa: E402

mismatches = 0
for period in day_payload["periods"]:
    if not (period["start"] and period["end"]):
        continue
    start = datetime.fromisoformat(period["start"])
    end = datetime.fromisoformat(period["end"])
    spans = [(datetime.fromisoformat(s["from"]), s["color"], s["makrooh"])
             for s in period["spans"]]
    moment = start
    while moment < end:
        want = prayer_logic.period_state(period["name"], start, end, moment)
        chosen = [s for s in spans if s[0] <= moment][-1]
        if (chosen[1], chosen[2]) != want:
            mismatches += 1
        moment += timedelta(seconds=30)
check("no second disagrees", mismatches, 0)

print("7b. the hours after midnight belong to last night's Isha")
# The one stretch of the day that belongs to the evening before. Asked at an explicit
# hour rather than whenever the suite runs: this broke in the field at 00:04 and every
# test here had happened to run before midnight, so nothing caught it. The countdown has
# nothing to count if no period covers the clock, and shows "--:--".
# Sunrise is 06:00 in the fixture and Duha opens 20 minutes later, so 06:10 is still
# الشروق's own window and 06:30 is already الضحى's.
for hour, minute, want in ((0, 30, "العشاء"), (2, 30, "العشاء"), (4, 30, "العشاء"),
                           (6, 10, "الشروق"), (6, 30, "الضحى"),
                           (13, 0, "الظهر"), (21, 0, "العشاء")):
    moment = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    payload = api.day_payload(moment.date(), moment)
    covering = [p["name"] for p in payload["periods"]
                if p["start"] and p["end"]
                and datetime.fromisoformat(p["start"]) <= moment
                < datetime.fromisoformat(p["end"])]
    check(f"at {hour:02d}:{minute:02d} exactly one period is running",
          len(covering), 1)
    check(f"and at {hour:02d}:{minute:02d} it is {want}",
          covering[0] if covering else None, want)

# Before Fajr that Isha period has to start the previous evening, not tonight.
small_hours = datetime.now().replace(hour=1, minute=0, second=0, microsecond=0)
payload = api.day_payload(small_hours.date(), small_hours)
isha = [p for p in payload["periods"] if p["name"] == "العشاء"][0]
check("its period began yesterday evening",
      datetime.fromisoformat(isha["start"]).date(),
      small_hours.date() - timedelta(days=1))
check("and runs to this morning's Fajr",
      datetime.fromisoformat(isha["end"]).date(), small_hours.date())
check("while the card still shows tonight's Isha",
      datetime.fromisoformat(isha["time"]).date(), small_hours.date())
check_true("and it still carries spans to colour it with", bool(isha["spans"]))

# A date being browsed is not today, and must not borrow the evening before it.
other = (datetime.now() + timedelta(days=3)).replace(hour=1, minute=0)
payload = api.day_payload(other.date(), small_hours)
isha = [p for p in payload["periods"] if p["name"] == "العشاء"][0]
check("a browsed date keeps its own Isha",
      datetime.fromisoformat(isha["start"]).date(), other.date())

print("8. any date can be asked for, and a bad one is refused")
tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
status, body, _ = get(f"/api/day?date={tomorrow}")
check("a future date", status, 200)
check("comes back as itself", json.loads(body)["date"], tomorrow)
status, _, _ = get("/api/day?date=not-a-date")
check("a malformed date is refused", status, 400)

print("9. the settings payload offers what the device really has")
status, body, _ = get("/api/settings")
check("GET /api/settings", status, 200)
settings = json.loads(body)
check("duha_time is read from config.ini", settings["values"]["duha_time"], 60)
check("a boolean comes back as one", settings["values"]["enable_duha_prayer"], True)
check("the quran folder is listed",
      settings["audio"]["quran_audio_checked"]["available"], ["one.mp3", "two.mp3"])
check("and what is ticked in it",
      settings["audio"]["quran_audio_checked"]["checked"], ["one.mp3"])
check("an empty folder lists nothing",
      settings["audio"]["duha_audio_checked"]["available"], [])
check_true("today's times are offered for the rules",
           settings["times"]["dhuhr"] == 12 * 60)
# The fixture's config.ini predates the choice, which is every device on its first boot
# of this release: it is offered as a fixed 9:45.
check("Athkar Elsabah defaults to a fixed time",
      (settings["values"]["athkar_elsabah_mode"], settings["values"]["athkar_elsabah_clock"]),
      ("clock", "09:45"))

print("10. a save writes exactly the keys it was given, and nothing else")
before = open(INI, encoding="utf-8").read()
status, reply = post("/api/settings", {"duha_time": 45}, origin=BASE)
check("POST /api/settings", status, 200)
check("reports saved", reply.get("saved"), True)
after = open(INI, encoding="utf-8").read()
# configparser.write always ends a section with a blank line, exactly as the Settings
# app's own save does, so that is not a difference between the two writers.
def lines(text):
    return [line for line in text.splitlines() if line.strip()]
changed = [line for line in lines(after) if line not in lines(before)]
check("one line differs", changed, ["duha_time = 45"])
check("and nothing was dropped",
      [line for line in lines(before) if line not in lines(after)],
      ["duha_time = 60"])

print("11. a no-change save leaves the file byte for byte")
status, _ = post("/api/settings", {"duha_time": 45}, origin=BASE)
check("accepted", status, 200)
check("file unchanged", open(INI, encoding="utf-8").read(), after)

print("12. the rules the touch screen enforces are enforced here too")
status, reply = post("/api/settings", {"duha_time": 5}, origin=BASE)
check("Duha under 20 minutes is refused", status, 400)
check_true("in the Settings app's own words",
           "20 دقيقة من صلاة الظهر" in reply["error"])
check("and nothing was written", open(INI, encoding="utf-8").read(), after)

status, reply = post("/api/settings", {"duha_time": 350}, origin=BASE)
check("Duha too close to sunrise is refused", status, 400)
check_true("with the sunrise wording", "بعد طلوع الشمس" in reply["error"])

status, reply = post("/api/settings", {"athkar_elsabah_mode": "after_fajr",
                                      "athkar_elsabah_time": 500}, origin=BASE)
check("Athkar Elsabah past Dhuhr is refused", status, 400)
check_true("naming both times", "وقت أذكار الصباح" in reply["error"])
# Both times sit inside an Arabic sentence. Without the isolates the bidi algorithm lays
# "12:20 PM" out as "PM 12:20" - the digits are weak, the marker is strong left-to-right -
# and the message reads wrong in a browser exactly as it would on the touch screen.
check("each time is wrapped in an LTR isolate", reply["error"].count("\u2066"), 2)
check("and each one is popped again", reply["error"].count("\u2069"), 2)
check_true("the isolate opens immediately before the digits",
           "\u20661" in reply["error"] or "\u20662" in reply["error"]
           or any(f"\u2066{d}" in reply["error"] for d in "0123456789"))

status, reply = post("/api/settings", {"athkar_elsabah_clock": "12:30"}, origin=BASE)
check("a fixed Athkar Elsabah past Dhuhr is refused", status, 400)
check_true("naming Fajr and Dhuhr", "صلاة الفجر" in reply["error"]
           and "صلاة الظهر" in reply["error"])
status, reply = post("/api/settings", {"athkar_elsabah_clock": "04:30"}, origin=BASE)
check("and so is one before Fajr", status, 400)
status, reply = post("/api/settings", {"athkar_elsabah_mode": "clock",
                                      "athkar_elsabah_time": 500}, origin=BASE)
check("minutes past Dhuhr are not checked while a fixed time is chosen", status, 200)
status, reply = post("/api/settings", {"athkar_elsabah_time": 240}, origin=BASE)
check("put back", status, 200)
check("and only the mode it was sent was added",
      [line for line in lines(open(INI, encoding="utf-8").read()) if line not in lines(after)],
      ["athkar_elsabah_mode = clock"])
after = open(INI, encoding="utf-8").read()

print("12b. the countdown page carries the mute control inside the counter")
_, body, _ = get("/countdown/")
page = body.decode("utf-8")
check_true("the page is full-bleed", 'class="full"' in page)
check_true("the mute button is inside the counter",
           page.index('id="mute"') > page.index('id="counter"')
           and page.index('id="mute"') < page.index("</main>"))
check_true("it is drawn as SVG", "SPEAKER_OFF" in page and "<svg" in page)
# The touch screen's glyphs are monochrome and take the page colour. A browser renders
# U+1F50A / U+1F507 as colour emoji that ignore `color`, so they could never go red when
# muted - which is why the page must not fall back to them.
check("no emoji speaker anywhere on the page",
      any(ch in page for ch in ("\U0001F50A", "\U0001F507")), False)
check_true("and its muted state is the app's red",
           "#dc3545" in get("/static/app.css")[1].decode("utf-8"))

print("12c. the palette is still the one the touch screen paints")
# The website's colours are copies of the app's, and copies drift. These are re-derived
# from prayer_times_gui/main.py itself - the constants by reading them out of the source,
# and the card shades by running the same QColor.darker()/lighter() calls apply_state
# makes. Change a colour in the app without changing api.py and this fails.
import re  # noqa: E402

GUI_SOURCE = open(os.path.join(REPO, VARIANT, "applications", "desktop",
                               "prayer_times_gui", "main.py"), encoding="utf-8").read()


def gui_const(name):
    found = re.search(rf'^{name}\s*=\s*"(#[0-9A-Fa-f]{{6}})"', GUI_SOURCE, re.M)
    return found.group(1) if found else None


check("the counter's green is the app's", api.COUNTDOWN_FILL["green"],
      gui_const("COUNTDOWN_BG_GREEN"))
check("the counter's red is the app's", api.COUNTDOWN_FILL["red"],
      gui_const("COUNTDOWN_BG_RED"))
check("the counter's makrooh is the app's", api.COUNTDOWN_FILL["makrooh"],
      gui_const("COUNTDOWN_BG_MAKROOH"))
# The counter has no beige: period_state returns it for the ordinary middle of a period,
# and there the app paints its neutral grey. Getting this wrong paints the countdown a
# colour the touch screen never shows.
check("and the ordinary stretch is the neutral grey, not beige",
      api.COUNTDOWN_FILL["beige"], gui_const("COUNTDOWN_BG_DEFAULT"))
check("the counter's text is white throughout", api.COUNTDOWN_TEXT, "#FFFFFF")
check("the idle card is the app's CARD_BG", api.CARD_IDLE["background"],
      gui_const("CARD_BG"))
check("its border is the app's CARD_BORDER", api.CARD_IDLE["border"],
      gui_const("CARD_BORDER"))
check("its text is the app's NAME_COLOR", api.CARD_IDLE["text"],
      gui_const("NAME_COLOR"))

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtGui import QColor
except ImportError:
    print("   (skipping the derived shades - no PyQt5 here)")
else:
    for name, base_hex in api.PERIOD_COLORS.items():
        base = QColor(base_hex)
        light = base.lightness() > 170
        style = api.CARD_ACTIVE[name]
        check(f"{name}: the card's base", style["from"].lower(), base.name().lower())
        # makrooh is flat on purpose, so its gradient has nowhere to travel to.
        want_to = (base.name() if name == "makrooh"
                   else base.darker(112 if light else 128).name())
        check(f"{name}: the card's far stop", style["to"].lower(), want_to.lower())
        want_border = (base.darker(112).name() if light else base.lighter(118).name())
        check(f"{name}: the card's border", style["border"].lower(),
              want_border.lower())
        check(f"{name}: makrooh alone is flat", style["flat"], name == "makrooh")
        check(f"{name}: the card's text", style["text"], api.PERIOD_TEXT[name])

        # The badge above the list is coloured from the same base by its own recipe:
        # a diagonal lighter(112) -> darker(122), with a lighter(118) border.
        badge = api.CARD_BADGE[name]
        check(f"{name}: the badge's near stop", badge["from"].lower(),
              base.lighter(112).name().lower())
        check(f"{name}: the badge's far stop", badge["to"].lower(),
              base.darker(122).name().lower())
        check(f"{name}: the badge's border", badge["border"].lower(),
              base.lighter(118).name().lower())
        check(f"{name}: the badge's text", badge["text"], api.PERIOD_TEXT[name])

print("13. a submission cannot invent a key or name a file that is not there")
status, reply = post("/api/settings", {"rm_rf": "yes"}, origin=BASE)
check("an unknown key is refused", status, 400)
status, reply = post("/api/settings", {"quran_audio_checked": ["nope.mp3"]}, origin=BASE)
check("an audio file that does not exist is refused", status, 400)
status, _ = post("/api/settings", {"friday_quran_position": "sideways"}, origin=BASE)
check("a bad position is refused", status, 400)
status, _ = post("/api/settings", {"listen_to_quran": "25:99"}, origin=BASE)
check("a bad clock is refused", status, 400)
status, _ = post("/api/settings", {"athkar_elsabah_mode": "whenever"}, origin=BASE)
check("a bad Athkar Elsabah mode is refused", status, 400)
status, _ = post("/api/settings", {"athkar_elsabah_clock": "9.45"}, origin=BASE)
check("and a bad Athkar Elsabah clock", status, 400)
status, _ = post("/api/settings", {"athkar_elsabah_clock": ""}, origin=BASE)
check("and an empty one - a fixed time always has one", status, 400)
status, _ = post("/api/settings", {"duha_time": "-5"}, origin=BASE)
check("a negative number is refused", status, 400)
check("still nothing written", open(INI, encoding="utf-8").read(), after)

print("14. an audio list really round-trips")
status, _ = post("/api/settings", {"quran_audio_checked": ["one.mp3", "two.mp3"]},
                 origin=BASE)
check("both ticked", status, 200)
_, body, _ = get("/api/settings")
check("and read back", json.loads(body)["audio"]["quran_audio_checked"]["checked"],
      ["one.mp3", "two.mp3"])
status, _ = post("/api/settings", {"quran_audio_checked": []}, origin=BASE)
check("none ticked", status, 200)
_, body, _ = get("/api/settings")
check("and read back empty",
      json.loads(body)["audio"]["quran_audio_checked"]["checked"], [])

print("14b. the Athkar Elsabah choice really round-trips")
status, _ = post("/api/settings", {"athkar_elsabah_mode": "clock",
                                  "athkar_elsabah_clock": "10:15"}, origin=BASE)
check("a fixed 10:15 is accepted", status, 200)
_, body, _ = get("/api/settings")
values = json.loads(body)["values"]
check("and read back", (values["athkar_elsabah_mode"], values["athkar_elsabah_clock"]),
      ("clock", "10:15"))
status, _ = post("/api/settings", {"athkar_elsabah_mode": "after_fajr"}, origin=BASE)
check("minutes after Fajr are accepted", status, 200)
_, body, _ = get("/api/settings")
values = json.loads(body)["values"]
check("and read back, keeping the fixed time for when it is chosen again",
      (values["athkar_elsabah_mode"], values["athkar_elsabah_clock"]),
      ("after_fajr", "10:15"))

print("14c. the no-internet warning is on unless switched off")
_, body, _ = get("/api/settings")
check("a device that never chose reads as on",
      json.loads(body)["values"]["enable_internet_warning"], True)
status, _ = post("/api/settings", {"enable_internet_warning": False}, origin=BASE)
check("switching it off is accepted", status, 200)
_, body, _ = get("/api/settings")
check("and read back off", json.loads(body)["values"]["enable_internet_warning"], False)
status, _ = post("/api/settings", {"enable_internet_warning": True}, origin=BASE)
check("and on again", status, 200)

print("15. a save runs apply_settings.sh, off the request")
deadline = datetime.now() + timedelta(seconds=20)
state = None
while datetime.now() < deadline:
    _, body, _ = get("/api/apply")
    state = json.loads(body)["state"]
    if state in ("ok", "failed"):
        break
check("apply finished", state, "ok")
check_true("and the script really ran", os.path.isfile(APPLY_MARKER))

print("16. a page from somewhere else cannot post")
status, reply = post("/api/settings", {"duha_time": 30}, origin="http://evil.example")
check("a foreign Origin is refused", status, 403)
check_true("with a reason", "cross-origin" in reply.get("error", ""))

print("17. mute, through a real subprocess")
status, body, _ = get("/api/mute")
check("GET /api/mute", status, 200)
check("starts unmuted", json.loads(body)["muted"], False)
check_true("the sink is reachable", json.loads(body)["sink_reachable"])

status, reply = post("/api/mute", {}, origin=BASE)
check("POST /api/mute", status, 200)
check("now muted", reply["muted"], True)
check_true("the flag file was written", os.path.isfile(mute_lib.MUTE_FLAG_FILE))
check_true("with a deadline in the future", reply["flag_until"] is not None)
check("the sink was really muted", open(SINK_STATE).read().strip(), "1")

status, reply = post("/api/mute", {}, origin=BASE)
check("toggles back", reply["muted"], False)
check("the flag is gone", os.path.isfile(mute_lib.MUTE_FLAG_FILE), False)
check("and the sink is restored", open(SINK_STATE).read().strip(), "0")

status, reply = post("/api/mute", {"muted": True}, origin=BASE)
check("an explicit mute", reply["muted"], True)
status, reply = post("/api/mute", {"muted": True}, origin=BASE)
check("asked for twice, still muted", reply["muted"], True)
post("/api/mute", {"muted": False}, origin=BASE)

print("17b. the app a device hands out may mute it from the public site, and nothing more")
APP_ORIGIN = "https://alsakina-berlin.pages.dev"


def raw(method, path, origin, body=None):
    request = urllib.request.Request(BASE + path, data=body, method=method,
                                     headers={"Origin": origin})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


status, _, headers = raw("OPTIONS", "/api/mute", APP_ORIGIN)
check("the preflight is answered", status, 204)
check("for that site", headers.get("Access-Control-Allow-Origin"), APP_ORIGIN)
check("including Local Network Access's question",
      headers.get("Access-Control-Allow-Private-Network"), "true")
check_true("and a POST", "POST" in headers.get("Access-Control-Allow-Methods", ""))
# The body is sent as text/plain, as the app sends it: a simple request, no preflight.
status, body, headers = raw("POST", "/api/mute", APP_ORIGIN, b"{}")
check("the app mutes", (status, json.loads(body)["muted"]), (200, True))
check("and may read the answer", headers.get("Access-Control-Allow-Origin"), APP_ORIGIN)
status, body, headers = raw("GET", "/api/mute", APP_ORIGIN)
check("it reads the state", (status, json.loads(body)["muted"]), (200, True))
check("with the header it needs", headers.get("Access-Control-Allow-Origin"), APP_ORIGIN)
status, body, _ = raw("POST", "/api/mute", APP_ORIGIN, b"{}")
check("and unmutes", json.loads(body)["muted"], False)
check("a preview deployment of the site too",
      raw("OPTIONS", "/api/mute", "https://1a2b3c.alsakina-berlin.pages.dev")[0], 204)
check("an app added from the old sakina-<city> site still reaches its device",
      raw("OPTIONS", "/api/mute", "https://sakina-berlin.pages.dev")[0], 204)
# Anyone can make a .pages.dev project: only our own sites, named in full, are let in.
for origin in ("https://evil.pages.dev", "https://alsakina-berlin.pages.dev.evil.example",
               "http://alsakina-berlin.pages.dev", "https://sakina-app.pages.dev",
               "https://alsakina-evil.pages.dev", "https://sakina-evil.pages.dev",
               "https://xalsakina-berlin.pages.dev", "https://a.b.alsakina-berlin.pages.dev"):
    check(f"{origin} is refused", raw("POST", "/api/mute", origin, b"{}")[0], 403)
    check(f"and gets no preflight", raw("OPTIONS", "/api/mute", origin)[0], 403)
# The app's settings page reads and saves the device's settings the same way - and they
# are checked the same way.
status, body, headers = raw("GET", "/api/settings", APP_ORIGIN)
check("the app reads the settings", (status, headers.get("Access-Control-Allow-Origin")),
      (200, APP_ORIGIN))
check_true("the real ones", "duha_time" in json.loads(body)["values"])
check("and may preflight a save", raw("OPTIONS", "/api/settings", APP_ORIGIN)[0], 204)
status, body, _ = raw("POST", "/api/settings", APP_ORIGIN, b'{"duha_time": -5}')
check("a bad value from the app is refused like any other", status, 400)
check_true("in words", bool(json.loads(body).get("error")))
check("its apply state is readable",
      raw("GET", "/api/apply", APP_ORIGIN)[2].get("Access-Control-Allow-Origin"), APP_ORIGIN)
check("anything else is not", raw("OPTIONS", "/api/day", APP_ORIGIN)[0], 403)
check("nor is it answered for the site",
      raw("GET", "/api/day", APP_ORIGIN)[2].get("Access-Control-Allow-Origin"), None)
check("a foreign site still may not save",
      raw("POST", "/api/settings", "https://evil.example", b'{"duha_time": 30}')[0], 403)

print("18. the touch screen would see that mute, because the flag is the state")
mute_lib.write_mute_flag()
check_true("shared.is_muted agrees", mute_lib.is_muted())
_, body, _ = get("/api/mute")
check_true("and so does the website", json.loads(body)["flag_until"] is not None)
mute_lib.clear_mute_flag()

print("19. with no speaker to reach, the mute falls back to stopping the player")
# The stub is made to fail rather than removed: a development machine may well have a
# real wpctl on PATH, and taking ours away would quietly hand the test to that one.
working_stub = open(WPCTL, encoding="utf-8").read()
with open(WPCTL, "w", encoding="utf-8") as handle:
    handle.write("#!/bin/bash\nexit 1\n")
try:
    status, reply = post("/api/mute", {"muted": True}, origin=BASE)
    check("the request still succeeds", status, 200)
    check_true("and the flag is still set", os.path.isfile(mute_lib.MUTE_FLAG_FILE))
    check("the sink is reported unreachable", reply["sink_reachable"], False)
    check_true("but the device is still reported muted, from the flag", reply["muted"])
    # "the speaker could not be reached" is not actionable on its own - what wpctl said
    # has to come back with it, or nobody can tell whether it is a missing binary, a
    # PipeWire that is not running, or the wrong XDG_RUNTIME_DIR.
    check_true("and it says why", bool(reply.get("reason")))
    check_true("naming the command that failed", "wpctl" in reply.get("reason", ""))
    check_true("and which runtime dir it looked in",
               "/run/user/" in reply.get("runtime_dir", ""))
finally:
    with open(WPCTL, "w", encoding="utf-8") as handle:
        handle.write(working_stub)
    mute_lib.clear_mute_flag()
    post("/api/mute", {"muted": False}, origin=BASE)

# A systemd service inherits no usable XDG_RUNTIME_DIR, and wpctl finds both the PipeWire
# socket and the session bus through it. This is not a "fill it in if blank" - the unit
# used to set it to /run/user/%U, systemd resolved %U to 0 on a real device even with
# User= set, and a wrong value that is present is worse than none. mute.py takes the
# running process's own uid whenever that directory exists.
check("XDG_RUNTIME_DIR is derived from this process's uid",
      os.environ.get("XDG_RUNTIME_DIR"), f"/run/user/{os.getuid()}")
check_true("and the session bus is named rather than left to autolaunch",
           os.environ.get("DBUS_SESSION_BUS_ADDRESS", "").startswith("unix:path=")
           or not os.path.exists(f"/run/user/{os.getuid()}/bus"))

# The case that actually shipped: an inherited value that is set, and wrong.
import importlib  # noqa: E402
_saved = dict(os.environ)
os.environ["XDG_RUNTIME_DIR"] = "/run/user/0"
importlib.reload(mute_lib)
check("a wrong inherited runtime dir is corrected, not kept",
      os.environ.get("XDG_RUNTIME_DIR"), f"/run/user/{os.getuid()}")
os.environ.clear()
os.environ.update(_saved)
importlib.reload(mute_lib)

print("20. the device names itself for a phone that cannot resolve .local")
status, body, _ = get("/api/device")
check("GET /api/device", status, 200)
info = json.loads(body)
check_true("a hostname", bool(info["hostname"]))
check_true("and an address or an honest null", "ip" in info)

print("20a. and which public site hands out its app, by the prayer table it uses")
from main import PUBLIC_SITES  # noqa: E402
sites = json.load(open(PUBLIC_SITES, encoding="utf-8"))
check("the sites map carries berlin", sites.get("برلين.csv"), "https://alsakina-berlin.pages.dev")
check("with no table recorded there is none", info["public_site"], None)
ini_before = open(INI, encoding="utf-8").read()
for label, want in (
        ("/home/x/Desktop/scheduler/config/prayers-config/برلين.csv",
         "https://alsakina-berlin.pages.dev"),
        ("/home/x/Desktop/some-other-city.csv", None)):
    with open(INI, "w", encoding="utf-8") as handle:
        handle.write(ini_before.replace("[Settings]\n",
                                        f"[Settings]\nprayer_csv_source_label = {label}\n"))
    check(f"{os.path.basename(label)} -> {want}",
          json.loads(get("/api/device")[1])["public_site"], want)
with open(INI, "w", encoding="utf-8") as handle:
    handle.write(ini_before)
check_true("the landing page offers it under the name the phone used",
           'location.hostname.endsWith(".local")' in home
           and "${info.public_site}/d/${encodeURIComponent(name)}/" in home)
check_true("and only on the device", home.index("if (window.DEVICE) {\n    Site.json(\"/api/device\")") > 0)

print("20b. a device's app opens settings and the mute on the device, or says it cannot")
app_js = get("/static/app.js")[1].decode("utf-8")
countdown = get("/countdown/")[1].decode("utf-8")
check_true("the device's own address", "fetch(`http://${host}.local${path}`" in app_js)
check_true("Chrome asks the device first, as a local-network request",
           'targetAddressSpace: "local"' in app_js and 'mode: "no-cors"' in app_js)
check_true("on Chrome the app opens its own settings page, which talks to the device",
           "if (owner && !Site.canAskDevice()) {" in home)
# Safari cannot check the wifi, so a note on every tap read as an error even on the
# device's wifi. iOS opens the page in a window over the app; the page says X is the way
# back - on the app's own list that read as a warning about the list.
check_true("elsewhere settings opens the device's /settings/",
           'document.querySelector("#to-settings").href = Site.devicePage(owner, "/settings/");'
           in home and "settings-note" not in home)
check_true("marked as opened from the app",
           "`http://${host}.local${path}?from=app`" in app_js)
check_true("which the device page answers at its top by saying X returns to the app",
           'get("from") !== "app"' in app_js
           and "للعودة إلى التطبيق اضغط ✕ في أعلى الشاشة." in app_js
           and "document.body.prepend(bar);" in app_js
           and "Site.backToAppHint();" in app_js)
check_true("kept on screen, not timed out",
           "setTimeout" not in
           app_js[app_js.index("function backToAppHint"):app_js.index("function noteSayer")])
check_true("and its back arrow, which would only lead further in, is taken away",
           'document.querySelectorAll("a.back, a.back-corner")' in app_js)
settings_page = get("/settings/")[1].decode("utf-8")
check_true("the settings page asks the device itself when it is in the app",
           "const api = owner ? (path, options) => Site.deviceJson(owner, path, options)"
           in settings_page)
check_true("and says so when the device is out of reach",
           'show("error", "أنت خارج شبكة الواي فاي الخاصة بالجهاز، الإعدادات غير متاحة.")'
           in settings_page)
check_true("and its settings page says so when the device is out of reach",
           "أنت خارج شبكة الواي فاي الخاصة بالجهاز، الإعدادات غير متاحة." in settings_page)
check_true("Chrome mutes and unmutes the device straight from the app",
           'Site.deviceJson(host, "/api/mute",\n' in countdown
           and 'method: "POST", body: "{}"' in countdown)
check_true("and shows its state once the permission is there",
           "Site.localNetworkAllowed().then((allowed) =>" in countdown)
check_true("a device that refuses, from an older release, is opened instead",
           "if (await Site.deviceAnswers(host)) location.href = target;" in countdown)
# Safari cannot send it, or check first, so there the speaker opens the device's own
# countdown, the same way settings does.
check_true("elsewhere the speaker opens the device's countdown",
           'button.addEventListener("click", () => { location.href = target; });' in countdown
           and 'Site.devicePage(host, "/countdown/")' in countdown)
check_true("and says so when it is out of reach",
           "أنت خارج شبكة الواي فاي الخاصة بالجهاز، كتم الصوت غير متاح." in countdown)
check_true("under the speaker, not at the foot of the page",
           'Site.noteSayer("#speaker-note", "speaker-note")' in countdown)
check_true("the speaker stays off the public site",
           countdown.index("} else if (Site.ownerHost()) {")
           < countdown.index('document.querySelector("#mute").remove();'))

print("20c. and it reports the version the daily page prints at its foot")
VERSION_FILE = os.path.join(SCHEDULER, "var", "installed_version")


def device_version():
    _, raw, _ = get("/api/device")
    return json.loads(raw)["version"]


# No file at all is the state of a device that has never taken an update.
check("no version file reads as a dash", device_version(), "—")

with open(VERSION_FILE, "w", encoding="utf-8") as handle:
    handle.write("1.3.0\n")
check("the file is what is reported", device_version(), "1.3.0")

# The point of reading it per request: check_updates.sh rewrites this file under a
# server that keeps running, and a value cached at startup would be the old one.
with open(VERSION_FILE, "w", encoding="utf-8") as handle:
    handle.write("1.4.0\n")
check("a version written under a running server is picked up", device_version(), "1.4.0")

for written in ("", "   ", "unknown"):
    with open(VERSION_FILE, "w", encoding="utf-8") as handle:
        handle.write(written)
    check(f"{written!r} reads as a dash", device_version(), "—")

os.remove(VERSION_FILE)

# The touch screen and the website must not be able to print different numbers.
with open(VERSION_FILE, "w", encoding="utf-8") as handle:
    handle.write("1.3.0\n")
from shared import device_info  # noqa: E402
check("and the shared reader agrees with the endpoint",
      device_info.installed_version(SCHEDULER), device_version())

DAILY_HTML = open(os.path.join(WEB_UI, "site", "daily", "index.html"),
                  encoding="utf-8").read()
check_true("the daily page has a place to put it", 'id="version"' in DAILY_HTML)
check_true("hidden until it is filled", 'class="version hidden"' in DAILY_HTML)
# A static site has no /api/device to ask; it shows the release baked into config.js.
version_js = DAILY_HTML[DAILY_HTML.index("function refreshVersion"):]
check_true("and it is asked for only on a device",
           version_js.index("if (!window.DEVICE)") < version_js.index('"/api/device"')
           and "return;\n    }\n    Site.json(\"/api/device\")" in version_js)

print("20d. everything the touch screen's Settings offers, the website offers")
import configparser as _cp  # noqa: E402
from shared import prayer_source as source_lib, settings_defaults, updates as updates_lib  # noqa: E402

INI_BEFORE = open(INI, encoding="utf-8").read()
CSV_BEFORE = open(CSV_PATH, encoding="utf-8").read()


def settings_section():
    parser = _cp.ConfigParser(interpolation=None)
    parser.read(INI, encoding="utf-8")
    return parser["Settings"]


def wait_for(predicate, seconds=15):
    end = datetime.now() + timedelta(seconds=seconds)
    while datetime.now() < end:
        if predicate():
            return True
        threading.Event().wait(0.2)
    return False


def apply_finished():
    return wait_for(lambda: json.loads(get("/api/apply")[1])["state"] != "running")


def calls(unit):
    try:
        return open(os.path.join(UNITS, unit + ".calls"), encoding="utf-8").read()
    except OSError:
        return ""


payload = json.loads(get("/api/settings")[1])

# The country and city table, for the device's time zone.
zones = {zone for _country, cities in payload["timezones"] for _city, zone in cities}
check_true("the zone table is offered, country by country", len(payload["timezones"]) > 100)
check_true("with the cities of a country that spans several",
           any(len(cities) > 1 for _country, cities in payload["timezones"]))
check_true("Europe/Berlin is one of them", "Europe/Berlin" in zones)
# Daylight saving follows the clock's zone now: nothing to choose, nothing to send.
check_true("the old choice is not offered",
           not {"enable_daylight_saving", "daylight_saving_timezone"} & set(payload["values"]))
with open(INI, "a", encoding="utf-8") as handle:
    handle.write("enable_daylight_saving = False\ndaylight_saving_timezone = Europe/Berlin\n")
check("an older page that still sends it saves the rest",
      post("/api/settings", {"duha_time": 61, "enable_daylight_saving": True,
                             "daylight_saving_timezone": "Mars/Olympus"})[0], 200)
apply_finished()
check("and the retired keys are dropped from config.ini",
      [k for k in settings_section() if k in ("enable_daylight_saving",
                                              "daylight_saving_timezone")], [])
check("while the rest is written", settings_section()["duha_time"], "61")

# The prayer-times file: offered by name, chosen by name.
offered = payload["prayer_source"]
check("the presets are offered by name, as the picker lists them",
      offered["options"], sorted(["برلين.csv", "آخن.csv", "bad.csv", "دمشق.csv"]))
check("the Desktop file is named", offered["reference"], source_lib.REFERENCE_NAME)
check("nothing chosen yet, nothing to restore", (offered["chosen"], offered["restore"]), (None, None))
check_true("the file in use is reported valid", offered["valid"])

# The fixture's file was never written by the app, so it may hold hand edits: asked first.
status, body = post("/api/prayer-source", {"name": "برلين.csv"})
check("a file the app did not write is asked about first", (status, body.get("saved")), (200, False))
check_true("in the Settings app's words", source_lib.HAND_EDITS_WARNING in body.get("confirm", ""))
check("and nothing is recorded until yes",
      settings_section().get(source_lib.SOURCE_LABEL_KEY), None)
marker_before = open(APPLY_MARKER).read().count("\n") if os.path.exists(APPLY_MARKER) else 0
status, body = post("/api/prayer-source", {"name": "برلين.csv", "confirmed": True})
check("yes copies it in", (status, body.get("saved"), body.get("chosen")), (200, True, "برلين.csv"))
check_true("the schedule is rebuilt at once", apply_finished()
           and open(APPLY_MARKER).read().count("\n") == marker_before + 1)
check("its path is recorded", settings_section()[source_lib.SOURCE_LABEL_KEY],
      os.path.join(PRESETS, "برلين.csv"))
check("with the hash of what was written", settings_section()[source_lib.HASH_KEY],
      source_lib.file_hash(CSV_PATH))
offered = json.loads(get("/api/settings")[1])["prayer_source"]
check("and reported as chosen, and as the one to restore",
      (offered["chosen"], offered["restore"]), ("برلين.csv", "برلين.csv"))
status, body = post("/api/prayer-source", {"name": "آخن.csv"})
check("a file the app wrote is replaced without asking", (status, body.get("saved")), (200, True))
apply_finished()
status, body = post("/api/prayer-source", {"name": "bad.csv"})
check("a file in no known format is refused in the picker's words",
      (status, body.get("error")), (400, "صيغة الملف المختار غير معروفة أو غير صالحة"))
check("and the record stays", os.path.basename(settings_section()[source_lib.SOURCE_LABEL_KEY]), "آخن.csv")
for name in ("../../config/config.ini", CSV_PATH, "", "nothing.csv"):
    check(f"no path is ever opened: {name!r}", post("/api/prayer-source", {"name": name})[0], 400)
with open(CSV_PATH, "a", encoding="utf-8") as handle:
    handle.write("\n")
check_true("a hand edit since is asked about again",
           post("/api/prayer-source", {"name": "برلين.csv"})[1].get("confirm"))
status, body = post("/api/prayer-source", {"restore": True})
check("restore copies the last file in again, over the edit",
      (status, body.get("chosen")), (200, "آخن.csv"))
apply_finished()
check("the edit is gone", open(CSV_PATH, encoding="utf-8").read(),
      open(os.path.join(PRESETS, "آخن.csv"), encoding="utf-8").read())

# Reset: the shipped defaults, the prayer file kept, then setup in its own unit.
post("/api/settings", {"duha_time": 90})
apply_finished()
recorded = settings_section()[source_lib.SOURCE_LABEL_KEY]
status, body = post("/api/reset", {})
check("reset answers at once, setup started", (status, body), (200, {"reset": True, "setup": True}))
want = settings_defaults.reset_values({}, os.path.join(SCHEDULER, "config", "default-config.ini"))
after = settings_section()
settings_only = {k: v for k, v in want.items() if not k.endswith("_audio_checked")}
check("every default is back", {k: after.get(k) for k in settings_only}, settings_only)
check("the prayer file's record is kept", after[source_lib.SOURCE_LABEL_KEY], recorded)
check("an event's files are those the defaults name, or all of them",
      after["quran_audio_checked"], "one.mp3,two.mp3")
check_true("setup runs in a unit of its own, told to skip its update check and to apply",
           "SCHEDULER_INIT_NO_UPDATE_CHECK=1 SCHEDULER_INIT_APPLY_SETTINGS=1 | /bin/bash"
           in calls(web.RESET_UNIT))
check("and is reported running", json.loads(get("/api/reset")[1])["running"], True)
check_true("until it ends", wait_for(lambda: not json.loads(get("/api/reset")[1])["running"]))
check("init.sh ran, with both", open(os.path.join(ROOT, "init-ran")).read(), "11\n")

# Updates.
info = json.loads(get("/api/update")[1])
check("the status is check_updates.sh's", info["status"]["installed"], "1.5.5")
check("the daily check's time, as the touch screen prints it",
      info["check_time"], api.minutes_to_clock(120))
check("nothing running", info["running"], False)
check("a version that was never listed is refused",
      post("/api/update", {"action": "target", "version": "1.5.6"})[0], 400)
first = json.loads(get("/api/update/versions")[1])
check_true("the list is fetched in the background", first["state"] in ("fetching", "ok"))
check_true("and arrives", wait_for(lambda: json.loads(get("/api/update/versions")[1])["state"] == "ok"))
versions = json.loads(get("/api/update/versions")[1])
check("newest first", versions["versions"], ["1.5.6", "1.5.5", "1.5.4", "1.5.3"])
check("with the approved one", versions["latest"], "1.5.6")
for bad in ("1.5.6; rm -rf /", "--rollback", "9.9.9"):
    check(f"not a listed version: {bad!r}",
          post("/api/update", {"action": "target", "version": bad})[0], 400)
check("an unknown action is refused", post("/api/update", {"action": "reboot"})[0], 400)

status, body = post("/api/update", {"action": "target", "version": "1.5.3"})
check("anything but the approved one is asked about, as it holds the device",
      (status, body.get("confirm")), (200, updates_lib.hold_question("1.5.3")))
check("and nothing has run", os.path.exists(os.path.join(ROOT, "update-ran")), False)
status, body = post("/api/update", {"action": "target", "version": "1.5.3", "confirmed": True})
check("yes starts it", (status, body), (200, {"started": True}))
check_true("the daily check is turned off first",
           "ENABLED=false" in open(os.path.join(SCHEDULER, "config", "update.conf")).read())
check_true("in a unit of its own, saying it came from the website",
           calls(web.UPDATE_UNIT).rstrip().endswith("check_updates.sh --remote --target 1.5.3"))
check("one at a time", post("/api/update", {"action": "now"})[0], 409)
check_true("reported running", json.loads(get("/api/update")[1])["running"])
check_true("until it ends", wait_for(lambda: not json.loads(get("/api/update")[1])["running"]))
check("and its result is the one the page reports",
      json.loads(get("/api/update")[1])["status"]["last_result"], "updated")

status, body = post("/api/update", {"action": "rollback", "version": "1.5.4"})
check("the kept backup is a restore, not a download - auto is already off, so no question",
      (status, body), (200, {"started": True}))
wait_for(lambda: not json.loads(get("/api/update")[1])["running"])
check("--rollback", open(os.path.join(ROOT, "update-ran")).read().splitlines()[-1],
      "--remote --rollback")

status, body = post("/api/update/auto", {"enabled": True})
check("turning the daily check on asks when it would move the device",
      body.get("confirm"), updates_lib.enable_question("1.5.5", "1.5.6"))
check_true("and changes nothing until yes",
           "ENABLED=false" in open(os.path.join(SCHEDULER, "config", "update.conf")).read())
status, body = post("/api/update/auto", {"enabled": True, "confirmed": True})
check("yes turns it on and moves it", body, {"saved": True, "started": True})
conf = open(os.path.join(SCHEDULER, "config", "update.conf")).read()
check_true("ENABLED=true, the PIN cleared", "ENABLED=true" in conf and "PIN=\n" in conf)
wait_for(lambda: not json.loads(get("/api/update")[1])["running"])
check("to the approved version", open(os.path.join(ROOT, "update-ran")).read().splitlines()[-1],
      "--remote --now")
check("off is off, nothing run", post("/api/update/auto", {"enabled": False})[1],
      {"saved": True, "started": False})
check_true("written", "ENABLED=false" in open(os.path.join(SCHEDULER, "config", "update.conf")).read())
check("a body that is not a switch is refused", post("/api/update/auto", {"enabled": "yes"})[0], 400)

# With nobody logged in there is no user systemd to start a job in.
open(os.path.join(ROOT, "no-user-systemd"), "w").close()
status, body = post("/api/update", {"action": "now"})
check("an update says to use the screen instead",
      (status, body.get("error")), (409, "تعذّر بدء التحديث من هنا، استخدم شاشة الجهاز."))
status, body = post("/api/reset", {})
check("a reset still resets, and rebuilds the schedule itself", (status, body),
      (200, {"reset": True, "setup": False}))
check_true("by applying", apply_finished())
os.remove(os.path.join(ROOT, "no-user-systemd"))

for path in ("/api/prayer-source", "/api/reset", "/api/update", "/api/update/versions",
             "/api/update/auto"):
    check_true(f"the handed-out app may call {path}", path in web.PUBLIC_APP_PATHS)
check("a stranger's page may not reset the device",
      post("/api/reset", {}, origin="http://evil.example")[0], 403)
for needle in ("/api/prayer-source", "/api/reset", "/api/update/auto", "/api/update/versions",
               "استعادة مواقيت المدينة",
               "إعادة ضبط الإعدادات", "تحديث تلقائي يومي", "الرجوع إلى إصدار سابق:"):
    check_true(f"the page offers {needle}", needle in settings_html)

with open(INI, "w", encoding="utf-8") as handle:
    handle.write(INI_BEFORE)
with open(CSV_PATH, "w", encoding="utf-8") as handle:
    handle.write(CSV_BEFORE)

print("20e. a recitation is uploaded into the folder chosen for it, from either screen")
from shared import audio_upload  # noqa: E402

MP3 = b"ID3\x04\x00" + b"\x00" * 2000
QURAN_DIR = os.path.join(SCHEDULER, "audio", "quran")


def upload(folder, name, body, replace=False, origin=None, length=None):
    query = urllib.parse.urlencode({"folder": folder, "name": name,
                                    "replace": "1" if replace else "0"})
    headers = {"Content-Type": "application/octet-stream"}
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(f"{BASE}/api/audio?{query}", data=body,
                                     headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


payload = json.loads(get("/api/settings")[1])
check("every event folder the device has is offered, in the screens' order",
      [folder for folder, _ in payload["audio_folders"]], list(audio_upload.FOLDER_LABELS))
check("each under its event's name", dict(payload["audio_folders"])["shorooq"], "الشروق")
check("a new name asks nothing", post("/api/audio/check", {"folder": "quran",
                                                           "name": "سورة-يس.mp3"}), (200, {}))
status, body = upload("quran", "سورة-يس.mp3", MP3)
check("it is saved", (status, body["saved"], body["name"]), (200, True, "سورة-يس.mp3"))
check("whole", open(os.path.join(QURAN_DIR, "سورة-يس.mp3"), "rb").read(), MP3)
check("and the answer lists it with the rest", body["available"],
      ["one.mp3", "two.mp3", "سورة-يس.mp3"])
check_true("unticked: a new file plays only once it is chosen and saved",
           "سورة-يس.mp3" not in json.loads(get("/api/settings")[1])
           ["audio"]["quran_audio_checked"]["checked"])
check("nothing half-written is left beside it",
      [n for n in os.listdir(QURAN_DIR) if n.startswith(".")], [])
status, body = post("/api/audio/check", {"folder": "quran", "name": "سورة-يس.mp3"})
check_true("a name already there is asked about first",
           status == 200 and "هل تريد استبداله" in body.get("confirm", "")
           and "القرآن اليومي" in body["confirm"])
check("and refused if sent without the answer", upload("quran", "سورة-يس.mp3", MP3)[0], 400)
check("replaced with it", upload("quran", "سورة-يس.mp3", MP3 + b"x", replace=True)[0], 200)
check("by the new file", os.path.getsize(os.path.join(QURAN_DIR, "سورة-يس.mp3")), len(MP3) + 1)

for label, folder, name, body, message in (
        ("a folder that is not an event's", "../config", "x.mp3", MP3, "المجلد المختار غير موجود"),
        ("a name that climbs out", "quran", "../x.mp3", MP3, "اسم الملف غير صالح"),
        ("a hidden name", "quran", ".x.mp3", MP3, "اسم الملف غير صالح"),
        ("anything but mp3", "quran", "x.wav", MP3, "يُقبل ملف صوتي بصيغة MP3 فقط"),
        ("a comma, which config.ini would split", "quran", "a,b.mp3", MP3,
         "اسم الملف يجب ألا يحتوي على فاصلة «,» — غيّر اسمه ثم أعد المحاولة"),
        ("a file that is not audio", "quran", "fake.mp3", b"<html>" * 50,
         "الملف المختار ليس ملفًا صوتيًا بصيغة MP3"),
        ("an empty file", "quran", "empty.mp3", b"", "الملف فارغ")):
    status, answer = upload(folder, name, body)
    check(f"{label} is refused", (status, answer.get("error")), (400, message))
check("and leaves nothing behind", sorted(os.listdir(QURAN_DIR)),
      ["one.mp3", "two.mp3", "سورة-يس.mp3"])
check("the check refuses the same", post("/api/audio/check", {"folder": "quran",
                                                              "name": "a,b.mp3"})[0], 400)
check("an MPEG frame with no tag is audio too", audio_upload.looks_like_mp3(b"\xff\xfb\x90"),
      True)

original_free = audio_upload.FREE_MARGIN_BYTES
audio_upload.FREE_MARGIN_BYTES = 1 << 60
check("a card without room for it is refused before anything is written",
      upload("quran", "big.mp3", MP3)[1].get("error"),
      "لا توجد مساحة كافية على بطاقة الذاكرة لهذا الملف")
audio_upload.FREE_MARGIN_BYTES = original_free

status, answer = upload("fajr", "دعاء.mp3", MP3, origin=APP_ORIGIN)
check("the handed-out app may upload", status, 200)
check("a stranger's page may not",
      upload("fajr", "x.mp3", MP3, origin="http://evil.example")[0], 403)
status, _, headers = raw("OPTIONS", "/api/audio", APP_ORIGIN)
check("its preflight is answered", status, 204)
for path in ("/api/audio", "/api/audio/check"):
    check_true(f"the handed-out app may call {path}", path in web.PUBLIC_APP_PATHS)

copied = os.path.join(ROOT, "usb-recitation.mp3")
with open(copied, "wb") as handle:
    handle.write(MP3)
check("the touch screen copies from the device the same way",
      audio_upload.copy(copied, audio_upload.target(SCHEDULER, "duha", "usb-recitation.mp3")),
      "usb-recitation.mp3")
check_true("and it is there", os.path.isfile(os.path.join(SCHEDULER, "audio", "duha",
                                                          "usb-recitation.mp3")))
gui = open(os.path.join(APPLICATIONS, "desktop", "scheduler_settings_gui", "main.py"),
           encoding="utf-8").read()
check_true("the Settings app offers it beside the internet warning",
           "main_layout.addWidget(self.build_internet_warning_section())\n"
           "        main_layout.addWidget(self.build_audio_upload_section())" in gui)
check_true("with a picker for a file on the device", "QFileDialog.getOpenFileName(" in gui
           and "audio_upload.copy(" in gui)
for needle in ("إدارة الملفات الصوتية", "رفع ملف", "حذف ملفات", "/api/audio/check",
               'type: "file"', "timeoutMs"):
    check_true(f"the page offers {needle}", needle in settings_html)
check_true("the app waits as long as the upload takes, not the usual ten seconds",
           "timeoutMs || DEVICE_CHECK_MS" in open(os.path.join(WEB_UI, "site", "app.js"),
                                                  encoding="utf-8").read())
for folder, name in (("fajr", "دعاء.mp3"), ("duha", "usb-recitation.mp3")):
    os.remove(os.path.join(SCHEDULER, "audio", folder, name))

print("20e2. recitations are deleted from a folder, asked about first, and unticked")
DELETE_INI_BEFORE = open(INI, encoding="utf-8").read()


def ini_value(key):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(INI, encoding="utf-8")
    return parser["Settings"].get(key)


def set_ini(**values):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(INI, encoding="utf-8")
    for key, value in values.items():
        parser["Settings"][key] = value
    with open(INI, "w", encoding="utf-8") as handle:
        parser.write(handle)


set_ini(quran_audio_checked="one.mp3,سورة-يس.mp3", enable_listen_to_quran="True")
status, body = post("/api/audio/delete", {"folder": "quran", "names": ["سورة-يس.mp3"]})
check_true("the files are named in the question, and nothing is deleted yet",
           status == 200 and "سورة-يس.mp3" in body.get("confirm", "")
           and "القرآن اليومي" in body["confirm"] and "لا يمكن التراجع" in body["confirm"]
           and os.path.isfile(os.path.join(QURAN_DIR, "سورة-يس.mp3")))
check_true("a ticked one is said to leave the list",
           "ستُزال من قائمة المجلد" in body["confirm"] and "فسيتم إيقافه" not in body["confirm"])
status, body = post("/api/audio/delete", {"folder": "quran", "names": ["سورة-يس.mp3"],
                                          "confirmed": True})
check("deleted", (status, body.get("deleted"), body.get("switched_off")),
      (200, ["سورة-يس.mp3"], ""))
check("gone from the folder and from the answer",
      (os.path.exists(os.path.join(QURAN_DIR, "سورة-يس.mp3")), body["available"]),
      (False, ["one.mp3", "two.mp3"]))
check("unticked in config.ini, the rest kept", ini_value("quran_audio_checked"), "one.mp3")
check("and the event stays on", ini_value("enable_listen_to_quran"), "True")

status, body = post("/api/audio/delete", {"folder": "quran", "names": ["one.mp3"]})
check_true("deleting the last ticked file says the event will stop",
           "فسيتم إيقافه" in body.get("confirm", ""))
for name in ("one.mp3", "two.mp3"):
    shutil.copy(os.path.join(QURAN_DIR, name), os.path.join(ROOT, "kept-" + name))
status, body = post("/api/audio/delete", {"folder": "quran", "names": ["one.mp3", "two.mp3"],
                                          "confirmed": True})
check("several at once", (status, sorted(body["deleted"]), body["available"]),
      (200, ["one.mp3", "two.mp3"], []))
check("the event left with nothing ticked is switched off",
      (body["switched_off"], ini_value("enable_listen_to_quran"), ini_value("quran_audio_checked")),
      ("enable_listen_to_quran", "False", ""))
check_true("and the schedule rebuilt for it", apply_finished())
for name in ("one.mp3", "two.mp3"):
    shutil.move(os.path.join(ROOT, "kept-" + name), os.path.join(QURAN_DIR, name))

for label, payload, message in (
        ("nothing chosen", {"folder": "quran", "names": []}, "لم يتم تحديد أي ملف للحذف"),
        ("a file that is not there", {"folder": "quran", "names": ["x.mp3"]},
         "الملف غير موجود: ⁨x.mp3⁩"),
        ("a folder that is not an event's", {"folder": "../config", "names": ["config.ini"]},
         "المجلد المختار غير موجود"),
        ("a name that climbs out", {"folder": "quran", "names": ["../fajr/x.mp3"]},
         "اسم الملف غير صالح"),
        ("anything but mp3", {"folder": "quran", "names": ["config.ini"]},
         "يُقبل ملف صوتي بصيغة MP3 فقط")):
    status, answer = post("/api/audio/delete", {**payload, "confirmed": True})
    check(f"{label} is refused", (status, answer.get("error")), (400, message))
check("one bad name deletes none of the others",
      post("/api/audio/delete", {"folder": "quran", "names": ["one.mp3", "x.mp3"],
                                 "confirmed": True})[0], 400)
check_true("and they are there", os.path.isfile(os.path.join(QURAN_DIR, "one.mp3")))
check("a stranger's page may not delete",
      post("/api/audio/delete", {"folder": "quran", "names": ["one.mp3"], "confirmed": True},
           origin="http://evil.example")[0], 403)
check_true("the handed-out app may", "/api/audio/delete" in web.PUBLIC_APP_PATHS)
check_true("the Settings app deletes through the same code",
           "audio_upload.delete_question(" in gui and "audio_upload.delete(" in gui
           and "إدارة الملفات الصوتية" in gui and "حذف الملفات المحددة" in gui)
with open(INI, "w", encoding="utf-8") as handle:
    handle.write(DELETE_INI_BEFORE)

print("20f. the clock's own time zone is changed from either screen, and the device reboots")
SUDO_CALLS = os.path.join(ROOT, "sudo-calls")


def sudo_calls():
    try:
        return open(SUDO_CALLS, encoding="utf-8").read().splitlines()
    except OSError:
        return []


check("the page is told the clock's zone", json.loads(get("/api/settings")[1])["os_timezone"],
      "Europe/Berlin")
check_true("and names it in Arabic from the same table, not by its id",
           "${zoneName(state.os_timezone)}" in settings_html
           and "ltr(now)" not in settings_html)
status, body = post("/api/os-timezone", {"zone": "Asia/Damascus"})
check_true("a new zone is asked about first, naming the country and the reboot",
           status == 200 and "سوريا" in body.get("confirm", "")
           and "يُعاد تشغيل الجهاز" in body["confirm"])
check("and nothing is changed before the answer", sudo_calls(), [])
open(os.path.join(ROOT, "applied-tz"), "w").close()
status, body = post("/api/os-timezone", {"zone": "Asia/Damascus", "confirmed": True})
check("yes changes it", (status, body), (200, {"rebooting": True, "zone": "Asia/Damascus"}))
check("after rebuilding the schedule for the new zone's daylight saving",
      open(os.path.join(ROOT, "applied-tz")).read(), "Asia/Damascus\n")
check("through the root helper, which reboots", sudo_calls(),
      ["-n /usr/local/sbin/scheduler-apply-system --timezone Asia/Damascus"])
for label, zone, message in (
        ("a zone not in the table", "Mars/Olympus", "المنطقة الزمنية غير معروفة"),
        ("something that is not a zone", "../../etc/passwd", "المنطقة الزمنية غير معروفة"),
        ("the zone it is already on", "Europe/Berlin", "ساعة الجهاز على هذه المنطقة الزمنية أصلًا")):
    status, body = post("/api/os-timezone", {"zone": zone, "confirmed": True})
    check(f"{label} is refused", (status, body.get("error")), (400, message))
check("and the helper is not asked", len(sudo_calls()), 1)

# The new country's city files, offered with the move.
with open(CSV_PATH, "w", encoding="utf-8") as handle:
    handle.write(open(os.path.join(PRESETS, "برلين.csv"), encoding="utf-8").read())
api.choose_prayer_source(INI, SCHEDULER, DESKTOP, "برلين.csv", confirmed=True)
csv_berlin, ini_berlin = open(CSV_PATH, encoding="utf-8").read(), open(INI, encoding="utf-8").read()
status, body = post("/api/os-timezone", {"zone": "Asia/Damascus"})
check("a move to Syria offers Syria's city files", body.get("prayer_files"), ["دمشق.csv"])
check_true("and the question says what the file replaces, without the reminder",
           source_lib.REFERENCE_NAME in body["confirm"] and "تذكّر" not in body["confirm"])
status, body = post("/api/os-timezone", {"zone": "Asia/Damascus", "confirmed": True,
                                         "prayer_file": "دمشق.csv"})
check("yes with Damascus's file", status, 200)
check("copies it into the Desktop file", open(CSV_PATH, encoding="utf-8").read(), DAMASCUS_CSV)
check("and records it", os.path.basename(settings_section()[source_lib.SOURCE_LABEL_KEY]),
      "دمشق.csv")
check("before the schedule is rebuilt for the new zone",
      open(os.path.join(ROOT, "applied-tz")).read().splitlines()[-1], "Asia/Damascus")
with open(OS_ZONE, "w", encoding="utf-8") as handle:
    handle.write("Asia/Damascus\n")
status, body = post("/api/os-timezone", {"zone": "Europe/Berlin"})
check("back to Germany: both German cities, exact zone first",
      sorted(body.get("prayer_files")), ["آخن.csv", "برلين.csv"])
with open(OS_ZONE, "w", encoding="utf-8") as handle:
    handle.write("Europe/Berlin\n")
with open(CSV_PATH, "w", encoding="utf-8") as handle:
    handle.write(csv_berlin)
with open(INI, "w", encoding="utf-8") as handle:
    handle.write(ini_berlin)
check("a file already of the new country asks nothing more",
      post("/api/os-timezone", {"zone": "Europe/Vienna"})[1].get("prayer_files"), [])
check("a country with no city file falls back to the reminder",
      "تذكّر" in post("/api/os-timezone", {"zone": "Asia/Riyadh"})[1]["confirm"], True)
status, body = post("/api/os-timezone", {"zone": "Asia/Damascus", "confirmed": True,
                                         "prayer_file": "برلين.csv"})
check("a file of another country is refused",
      (status, body.get("error")), (500, "ملف المواقيت المختار ليس من مدن هذه المنطقة"))
check("keeping the file is a plain change",
      post("/api/os-timezone", {"zone": "Asia/Damascus", "confirmed": True,
                                "prayer_file": ""})[0], 200)
check("and leaves it", open(CSV_PATH, encoding="utf-8").read(), csv_berlin)
open(os.path.join(ROOT, "sudo-fails"), "w").close()
status, body = post("/api/os-timezone", {"zone": "Asia/Damascus", "confirmed": True,
                                         "prayer_file": "دمشق.csv"})
check_true("a helper that refuses is reported, not taken for a reboot",
           status == 500 and "تعذّر تغيير المنطقة الزمنية" in body.get("error", ""))
check("and the prayer file it copied in is put back", open(CSV_PATH, encoding="utf-8").read(),
      csv_berlin)
check("with its record", open(INI, encoding="utf-8").read(), ini_berlin)
check("and the schedule is rebuilt again for the zone the clock is still on",
      open(os.path.join(ROOT, "applied-tz")).read().splitlines()[-2:], ["Asia/Damascus", ""])
os.remove(os.path.join(ROOT, "sudo-fails"))
check("a stranger's page may not change it",
      post("/api/os-timezone", {"zone": "Asia/Damascus", "confirmed": True},
           origin="http://evil.example")[0], 403)
check_true("the handed-out app may", "/api/os-timezone" in web.PUBLIC_APP_PATHS)
for needle in ("المنطقة الزمنية للجهاز", "/api/os-timezone", "os_country",
               "تغيير المنطقة الزمنية وإعادة التشغيل"):
    check_true(f"the page offers {needle}", needle in settings_html)
check_true("the Settings app offers it in place of the daylight-saving choice",
           "main_layout.addWidget(self.build_os_timezone_section())" in gui
           and "build_daylight_saving_section" not in gui
           and "os_timezone.change(self.zone, TIMEZONE_COUNTRIES, MAIN_DIR, DESKTOP_DIR, self.preset)" in gui)
check_true("and the page has no daylight-saving choice left",
           "enable_daylight_saving" not in settings_html and "dst_country" not in settings_html)

print("21. a request for nothing in particular is a 404, not a crash")
for path in ("/nope", "/api/nope", "/api/day/extra"):
    status, _, _ = get(path)
    check(f"{path} is 404", status, 404)
status, _ = post("/api/nope", {}, origin=BASE)
check("POST to nothing is 404", status, 404)

print("22. the prayer map is re-read when it changes underneath")
_, body, _ = get("/api/day")
first = json.loads(body)["periods"][0]["clock"]
rows = [dict(r, Fajr="04:30") for r in ROWS]
with open(os.path.join(SCHEDULER, "config", "prayer_times_map.py"), "w",
          encoding="utf-8") as handle:
    handle.write("prayerTimes = " + repr(rows))
os.utime(os.path.join(SCHEDULER, "config", "prayer_times_map.py"), None)
_, body, _ = get("/api/day")
second = json.loads(body)["periods"][0]["clock"]
check("the new Fajr is shown without a restart", (first, second),
      (" 5:00 AM", " 4:30 AM"))

print("23. the static build carries no way to touch the device")
OUT = os.path.join(ROOT, "site")
build = subprocess.run([sys.executable,
                        os.path.join(REPO, "tools", "build_static_site.py"),
                        "--scheduler-dir", SCHEDULER, "--out", OUT,
                        "--year", str(datetime.now().year)],
                       capture_output=True, text=True)
check("the build runs", build.returncode, 0)
check("the settings page is not at the public root",
      os.path.isdir(os.path.join(OUT, "settings")), False)
check_true("only in the app a device hands out",
           os.path.isfile(os.path.join(OUT, "device", "settings", "index.html")))
check("the daily list is the landing page, not a folder",
      (os.path.isdir(os.path.join(OUT, "daily")),
       'id="rows"' in open(os.path.join(OUT, "index.html"), encoding="utf-8").read()),
      (False, True))
check_true("the countdown comes along",
           os.path.isfile(os.path.join(OUT, "countdown", "index.html")))
YEAR_FILE = os.path.join(OUT, "data", f"{datetime.now().year}.json")
check_true("a year of data is written", os.path.isfile(YEAR_FILE))
check("and only the year the device's map is for",
      sorted(os.listdir(os.path.join(OUT, "data"))), [f"{datetime.now().year}.json"])
config_js = open(os.path.join(OUT, "static", "config.js"), encoding="utf-8").read()
check_true("DEVICE is false", "window.DEVICE = false" in config_js)
check_true("and the data is the baked file", "/data/{year}.json" in config_js)

print("23b. and the app a device hands out, at /d/<name>/")
OWNER = os.path.join(OUT, "device")
for page in ("index.html", os.path.join("countdown", "index.html")):
    check_true(f"device/{page} is written", os.path.isfile(os.path.join(OWNER, page)))
owner_home = open(os.path.join(OWNER, "index.html"), encoding="utf-8").read()
owner_countdown = open(os.path.join(OWNER, "countdown", "index.html"),
                       encoding="utf-8").read()
check_true("its manifest is its own, beside the page",
           'rel="manifest" href="manifest.webmanifest"' in owner_home
           and 'rel="manifest" href="../manifest.webmanifest"' in owner_countdown)
check_true("so is its icon", 'rel="apple-touch-icon" href="icon-256.png"' in owner_home)
owner_manifest = json.load(open(os.path.join(OWNER, "manifest.webmanifest"),
                                encoding="utf-8"))
# Relative to the manifest's own address, which is what starts each device's app at its
# own /d/<name>/.
check("it starts where it was installed from",
      (owner_manifest["start_url"], owner_manifest["scope"]), ("./", "./"))
check("and is named «السكينة»", owner_manifest["name"], "السكينة")
check_true("iOS is given the same name",
           'apple-mobile-web-app-title" content="السكينة"' in owner_home)
for icon in owner_manifest["icons"]:
    check_true(f"device manifest icon {icon['src']} resolves",
               os.path.isfile(os.path.join(OWNER, icon["src"])))
check_true("the public app keeps the public name",
           'apple-mobile-web-app-title" content="السكينة"'
           in open(os.path.join(OUT, "index.html"), encoding="utf-8").read())
# Chrome's install dialog only installs the page it is called from, so the page the
# device's button opens is the one that carries the install button.
check_true("the app's page offers to install itself",
           'id="app-install-button"' in owner_home and "beforeinstallprompt" in owner_home
           and "if (owner && !Site.installedApp())" in owner_home)
check_true("and on an iPhone the same button shows the way through Safari's menu",
           'id="ios-guide"' in owner_home and "if (Site.isIosSafari()) {\n            guide" in owner_home)
# The city under the title is a list of every city the site carries. A change is asked
# first, and in a device's app the page says the device keeps its own table.
check_true("the city is chosen from a list in place of its name",
           "if (Site.cities().length > 1)" in owner_home
           and 'document.querySelector("#place").replaceChildren(pick);' in owner_home)
check_true("nothing changes before نعم",
           'addEventListener("change", () => {' in owner_home
           and 'querySelector("#city-yes").addEventListener("click", () => show(select.value));'
           in owner_home
           and "هل تريد تغيير المدينة من" in owner_home)
check_true("and لا puts the list back",
           "select.value = current.id;" in owner_home
           and 'querySelector("#city-no").addEventListener("click", keep);' in owner_home)
check_true("the window says the device's file is not changed, in a device's app only",
           "هذا التغيير لا يغيّر ملف الإعدادات في الجهاز" in owner_home
           and 'if (fromDevice) {\n        document.querySelector("#city-device-note")'
           in owner_home)
check_true("another city than the device's says so, with a way straight back",
           "هذه المدينة مختلفة عن المضبوطة في الجهاز. للإبقاء عليها نفسها بدّل إلى" in owner_home
           and "show(home.id);" in owner_home)
check_true("the choice is applied before any page reads the data",
           app_js.index("Site.applyCity();") < app_js.index("Site.backToAppHint();")
           and "window.DEVICE ? [] : window.CITIES" in app_js)
redirects = open(os.path.join(OUT, "_redirects"), encoding="utf-8").read().splitlines()
check("every /d/<name>/ is served from device/", redirects,
      ["/d/:name /d/:name/ 301", "/d/:name/ /device/ 200",
       "/d/:name/* /device/:splat 200"])

print("23c. the offline copy holds every page and year")
worker = open(os.path.join(OUT, "sw.js"), encoding="utf-8").read()
kept = json.loads(worker[worker.index("const FILES = ") + len("const FILES = "):
                         worker.index(";\nconst NETWORK_WAIT_MS")])
missing = [f for f in kept
           if not os.path.isfile(os.path.join(OUT, f.lstrip("/"), "index.html")
                                 if f.endswith("/") else os.path.join(OUT, f.lstrip("/")))]
check("every file it keeps exists", missing, [])
for needed in ("/", "/countdown/", "/device/", "/device/countdown/",
               f"/data/{datetime.now().year}.json", "/static/app.js"):
    check_true(f"it keeps {needed}", needed in kept)
check_true("its version is filled in", "__VERSION__" not in worker
           and re.search(r'const CACHE = "sakina-[0-9a-f]{12}"', worker) is not None)
# The icons live in config/icons/ on a device and are served from there, so copytree
# does not bring them - a static copy without this step renders fine and still gets a
# blank glyph on a phone's home screen, which is the whole point of having them.
for name in ("icon-32.png", "icon-128.png", "icon-256.png", "manifest.webmanifest"):
    check_true(f"the static copy carries {name}",
               os.path.isfile(os.path.join(OUT, "static", name)))
static_manifest = json.load(open(os.path.join(OUT, "static", "manifest.webmanifest"),
                                 encoding="utf-8"))
for icon in static_manifest["icons"]:
    check_true(f"static manifest icon {icon['src']} resolves",
               os.path.isfile(os.path.join(OUT, "static", icon["src"])))

baked = json.load(open(YEAR_FILE, encoding="utf-8"))
check_true("the year has days in it", len(baked["days"]) > 360)
check_true("and they carry spans",
           all(p["spans"] for p in list(baked["days"].values())[0] if p["start"]))

print("24. nothing in the static output asks a server for anything")
offenders = []
for folder, _, files in os.walk(OUT):
    for name in files:
        if not name.endswith((".html", ".js")):
            continue
        text = open(os.path.join(folder, name), encoding="utf-8").read()
        for needle in ("/api/settings", "/api/mute", "/api/apply", "/api/device"):
            # The countdown carries its mute code, guarded by DEVICE, and the device app's
            # pages reach the device only as Site.ownerHost(). What must not survive is any
            # call made unconditionally.
            if (needle in text and "window.DEVICE" not in text
                    and "Site.ownerHost()" not in text):
                offenders.append(f"{name} calls {needle}")
check("no unguarded device call", offenders, [])

server.shutdown()
shutil.rmtree(ROOT, ignore_errors=True)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)} of {CHECKS} checks)")
    print("\n".join(FAILURES))
    sys.exit(1)
print(f"ALL PASS ({CHECKS} checks)")
