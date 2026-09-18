#!/usr/bin/env python3
"""The website, against a fixture device tree. No network, no real Raspberry Pi.

Starts the real server on a high port with a fake scheduler directory under it, then
drives it the way a browser does. The mute calls reach a `wpctl` that is a shell script
on PATH, so the fallback paths are exercised without a sound card.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
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
            "logs", "var", "audio/quran", "audio/fajr", "audio/duha",
            "audio/tahajjud", "audio/athkar_elsabah", "audio/athkar_elmasa",
            "audio/friday_quran", "audio/shorooq", "audio/dhuhr", "audio/asr",
            "audio/maghrib", "audio/isha"):
    os.makedirs(os.path.join(SCHEDULER, sub), exist_ok=True)

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
enable_daylight_saving = False
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
    handle.write(f'#!/bin/bash\necho "applied settings"\ndate >> "{APPLY_MARKER}"\n')
os.chmod(APPLY, 0o755)

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
for path, needle in (("/", "باقي للصلاة"),
                     ("/countdown/", "id=\"digits\""),
                     ("/daily/", "قائمة اليومية للصلوات"),
                     ("/settings/", "الاعدادات")):
    status, body, headers = get(path)
    check(f"GET {path}", status, 200)
    check_true(f"{path} contains {needle}", needle in body.decode("utf-8"))
    check(f"{path} is html", headers["Content-Type"], "text/html; charset=utf-8")

print("2. the home page links to all three, and to nothing else")
_, body, _ = get("/")
home = body.decode("utf-8")
for target in ("/countdown/", "/daily/", "/settings/"):
    check_true(f"home links to {target}", f'href="{target}"' in home)

print("3. a typed address without the trailing slash still lands")
status, _, headers = get("/countdown", follow=False)
check("GET /countdown redirects", status, 301)
check("to /countdown/", headers["Location"], "/countdown/")

print("4. the assets, and nothing else, are reachable")
for name, ctype in (("app.css", "text/css; charset=utf-8"),
                    ("app.js", "application/javascript; charset=utf-8"),
                    ("config.js", "application/javascript; charset=utf-8")):
    status, _, headers = get(f"/static/{name}")
    check(f"GET /static/{name}", status, 200)
    check(f"{name} content type", headers["Content-Type"], ctype)

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

status, reply = post("/api/settings", {"athkar_elsabah_time": 500}, origin=BASE)
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
check("the settings page is not copied", os.path.isdir(os.path.join(OUT, "settings")),
      False)
check_true("a year of data is written",
           os.path.isfile(os.path.join(OUT, "data", "year.json")))
config_js = open(os.path.join(OUT, "static", "config.js"), encoding="utf-8").read()
check_true("DEVICE is false", "window.DEVICE = false" in config_js)
check_true("and the data is the baked file", "/data/year.json" in config_js)
static_home = open(os.path.join(OUT, "index.html"), encoding="utf-8").read()
check("the home page has no settings link", "/settings/" in static_home, False)
check_true("but still has the other two",
           "/countdown/" in static_home and "/daily/" in static_home)
baked = json.load(open(os.path.join(OUT, "data", "year.json"), encoding="utf-8"))
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
            # The countdown page still carries its mute code, guarded by DEVICE. What
            # must not survive is any call made unconditionally.
            if needle in text and "window.DEVICE" not in text:
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
