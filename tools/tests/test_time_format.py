"""Prayer times are shown on a 12-hour clock, on the wall display and in Settings alike.

The two apps format times independently - they share no code - so this pins both against
the same table, and guards the one thing that must not follow: config.ini keeps 24-hour
values, because the athan scheduler parses them.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_time_format.py
"""
import os, sys, importlib.util, configparser
from datetime import datetime, date, timedelta

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
PRAYER_GUI = os.path.join(SCHEDULER, "applications/desktop/prayer_times_gui/main.py")
SETTINGS_GUI = os.path.join(SCHEDULER, "applications/desktop/scheduler_settings_gui/main.py")
SETTINGS_INI_FILE = os.path.join(SCHEDULER, "config/config.ini")

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFontMetrics, qGray
app = QApplication(sys.argv)

page = load(PRAYER_GUI, "prayer_times_gui")
gui = load(SETTINGS_GUI, "settings_app")


def settings_clock(minutes):
    """What the Settings app shows, without the invisible isolate it wraps it in."""
    return gui.ControlApp.minutes_to_clock(None, minutes).strip("\u2066\u2069")

# 24-hour input, then what the wall display shows and what the Settings app prints. The
# display pads the hour so the colons line up down the card list. The Settings labels have
# no column to line up with, so no pad.
CASES = [
    ((0, 0),   "12:00 AM", "12:00 AM"),   # midnight reads 12, never 0
    ((0, 7),   "12:07 AM", "12:07 AM"),
    ((5, 12),  " 5:12 AM", "5:12 AM"),    # the leading zero is gone
    ((7, 11),  " 7:11 AM", "7:11 AM"),
    ((11, 59), "11:59 AM", "11:59 AM"),   # last minute of the morning
    ((12, 0),  "12:00 PM", "12:00 PM"),   # noon reads 12, and is PM
    ((12, 59), "12:59 PM", "12:59 PM"),
    ((13, 0),  " 1:00 PM", "1:00 PM"),    # the hour rolls over, the marker does not
    ((18, 52), " 6:52 PM", "6:52 PM"),
    ((23, 59), "11:59 PM", "11:59 PM"),
]

print("1. the wall display's daily page")
for (hour, minute), on_page, _ in CASES:
    chk(f"{hour:02d}:{minute:02d}",
        page.clock_12h(datetime(2026, 6, 1, hour, minute)), on_page)

print("2. every row is the same width, which is what keeps the colons in a column")
widths = {len(page.clock_12h(datetime(2026, 6, 1, h, m))) for (h, m), _, _ in CASES}
chk("one width for all of them", len(widths), 1)

print("3. the colons line up down the list, on the rendered card and not just in the string")
# The character count was equal once while the screen was visibly ragged, so measure the
# widget rather than trusting the string.
MAP_FILE = os.path.join(HERE, "daily_map.py")
today = date.today()
open(MAP_FILE, "w", encoding="utf-8").write(
    "prayerTimes = [\n" + ",\n".join(
        '{"Month": %d, "Day": %d, "Fajr": "05:12", "Sunrise": "06:41", "Dhuhr": "12:18",'
        ' "Asr": "15:44", "Maghrib": "18:52", "Isha": "20:14"}'
        % ((today + timedelta(days=offset)).month, (today + timedelta(days=offset)).day)
        for offset in (-1, 0, 1)) + "\n]\n")

spec = importlib.util.spec_from_file_location("page_render", PRAYER_GUI)
page_mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(page_mod)
page_mod.PRAYER_MAP_FILE = MAP_FILE
page_mod.load_prayer_times()
page_view = page_mod.DailyPrayersPage()
page_view.resize(800, 480); page_view.refresh(); page_view.show()
app.processEvents()

# Without this the cards could all be showing "--:--" and every assertion below would
# pass while saying nothing. That is exactly how the first version of this test lied.
shown = {page_view.cards[n].time_label.text()[-2:] for n in page_mod.dailyPrayerOrder}
chk("the page really is showing times", shown, {"AM", "PM"})

columns = set()
for name in page_mod.dailyPrayerOrder:
    card = page_view.cards[name]
    if card.state and card.state[0]:
        continue                          # the running prayer is drawn larger on purpose
    text = card.time_label.text()
    origin = card.time_label.mapTo(page_view, card.time_label.rect().topLeft())
    metrics = QFontMetrics(card.time_label.font())
    columns.add(origin.x() + metrics.horizontalAdvance(text[:text.index(":")]))
chk("one colon column down the list", len(columns), 1)

print("4. the marker starts in the same column on every row")
# Measured off the widget, not the string: the pad is what makes " 5:12 AM" and
# "12:18 PM" the same width, and only the rendered card proves it held.
marker_columns = set()
for name in page_mod.dailyPrayerOrder:
    card = page_view.cards[name]
    if card.state and card.state[0]:
        continue
    text = card.time_label.text()
    origin = card.time_label.mapTo(page_view, card.time_label.rect().topLeft())
    metrics = QFontMetrics(card.time_label.font())
    marker_columns.add(origin.x() + metrics.horizontalAdvance(text[:text.index(" ", 1)]))
chk("AM and PM start at one x", len(marker_columns), 1)
chk("and it is to the right of the colons", min(marker_columns) > max(columns), True)

os.remove(MAP_FILE)

print("5. the Settings app agrees, without the pad")
for (hour, minute), _, in_settings in CASES:
    chk(f"{hour:02d}:{minute:02d}", settings_clock(hour * 60 + minute), in_settings)

print("6. a time that falls outside the day is wrapped into it")
# Tahajjud is Fajr minus up to five hours, which goes negative on a summer Fajr, and
# Athkar Elmasa is Maghrib plus up to five, which runs past midnight. Both are reachable
# from the spin boxes, and both used to be shown as -2:00 and 26:00.
chk("two hours before midnight", settings_clock(-120), "10:00 PM")
chk("one minute before midnight", settings_clock(-1), "11:59 PM")
chk("two hours after midnight", settings_clock(26 * 60), "2:00 AM")
chk("exactly midnight, the next day", settings_clock(24 * 60), "12:00 AM")

print("7. a duration is not a clock time and keeps its leading zero")
# The countdown page and the daily page's badge both show time remaining. Reading "1:00 م"
# where "01:00 left" was meant would be the worst possible way to get this wrong.
remaining = 65
chk("65 minutes still reads 01:05", f"{remaining // 60:02d}:{remaining % 60:02d}", "01:05")

print("8. config.ini still carries a 24-hour clock for the scheduler")
# listen_to_quran is the one clock time this app writes - everything else it stores is
# an offset in minutes. The athan scheduler parses it, so it must not follow the display.
saved_ini = open(SETTINGS_INI_FILE, encoding="utf-8").read()
gui.arabic_info = lambda parent, title, text: None
gui.arabic_error = lambda parent, title, text: None
w = gui.ControlApp()

w.cron_hour_spin.setValue(16)
w.cron_min_spin.setValue(5)
chk("saving succeeds", w.save_settings(show_message=False), True)

written = configparser.ConfigParser()
written.read(SETTINGS_INI_FILE, encoding="utf-8")
value = written["Settings"].get("listen_to_quran", "")
chk("16:05 is stored as 16:05, not as 4:05 PM", value, "16:05")
chk("and carries no marker", ("AM" in value or "PM" in value), False)

print("9. but the same time is shown to the reader on a 12-hour clock")
# "4:05 PM" is one left-to-right run, so the Arabic sentence around it must not break it
# apart or reorder it. Read the laid-out line back rather than assuming.
from PyQt5.QtGui import QTextLayout
from PyQt5.QtCore import Qt as _Qt
from PyQt5.QtGui import QFont as _QFont

def on_screen(text):
    lay = QTextLayout(text, _QFont("Amiri", 18))
    opt = lay.textOption(); opt.setTextDirection(_Qt.RightToLeft); lay.setTextOption(opt)
    lay.beginLayout(); line = lay.createLine(); line.setLineWidth(2000); lay.endLayout()
    return "".join(c for _, c in sorted((line.cursorToX(i)[0], text[i])
                                        for i in range(len(text)))
                   if c not in "\u2066\u2069\u200e")

# The label is an Arabic sentence with a time inside it. Bidi splits "4:35 AM" in two on
# its own - weak digits, strong Latin marker - and lays the halves out right to left, so
# the screen reads "AM 4:35". The isolate is what stops that, and only the laid-out line
# can show whether it held.
sentence = f"وقت صلاة الضحى: {w.minutes_to_clock(7 * 60 + 11)}"
visual = on_screen(sentence)
chk("the time is wrapped in an isolate",
    w.minutes_to_clock(7 * 60 + 11).startswith("\u2066"), True)
chk("both parts survive", "7:11" in visual and "AM" in visual, True)
chk("and the marker is drawn to the right of the digits",
    visual.index("7:11") < visual.index("AM"), True)

chk("16:05 reads 4:05 PM", settings_clock(16 * 60 + 5), "4:05 PM")

# The suite leaves the device's own settings as it found them.
open(SETTINGS_INI_FILE, "w", encoding="utf-8").write(saved_ini)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
