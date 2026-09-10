"""Surat Al-Kahf on Fridays: the scheduler that places it, the player that finds its
audio, and the Settings section that configures it.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_friday_quran.py
"""
import os, sys, importlib.util, configparser, subprocess
from datetime import date

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
SERVICE = os.path.join(SCHEDULER, "applications/services/audio_event_scheduler/main.py")
APP = os.path.join(SCHEDULER, "applications/desktop/scheduler_settings_gui/main.py")
PLAY_AUDIO = os.path.join(SCHEDULER, "config/scripts/play_audio.sh")
SETTINGS_INI_FILE = os.path.join(SCHEDULER, "config/config.ini")
FRIDAY = 4

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


# ---------------------------------------------------------------------------
# The scheduler
# ---------------------------------------------------------------------------
service = load(SERVICE, "audio_event_scheduler")

MAP_FILE = os.path.join(HERE, "friday_map.py")
INI_FILE = os.path.join(HERE, "friday_config.ini")
service.PRAYER_PYTHON_MAP_FILE = MAP_FILE
service.SETTINGS_INI_FILE = INI_FILE

# A month of days at fixed times, so the only thing that varies between rows is the date.
# The year is whatever the scheduler is running in - it takes it from the clock - so which
# rows are Fridays is worked out here the same way rather than hard-coded.
YEAR = date.today().year
DAYS = [date(YEAR, 6, d) for d in range(1, 29)]
FRIDAYS = [d for d in DAYS if d.weekday() == FRIDAY]

def write_map(dhuhr="13:00", asr="17:00", sunrise="05:30"):
    rows = ",\n".join(
        '{"Month": %d, "Day": %d, "Fajr": "04:00", "Sunrise": "%s", "Dhuhr": "%s", '
        '"Asr": "%s", "Maghrib": "21:00", "Isha": "22:30"}' % (d.month, d.day, sunrise, dhuhr, asr)
        for d in DAYS)
    open(MAP_FILE, "w").write("prayerTimes = [\n" + rows + "\n]\n")

def write_ini(**overrides):
    settings = {
        "enable_listen_to_quran": "False",
        "enable_friday_quran": "True",
        "friday_quran_position": "after",
        "friday_quran_time": "60",
        "friday_quran_audio_checked": "kahf.mp3",
    }
    settings.update({k: str(v) for k, v in overrides.items()})
    parser = configparser.ConfigParser()
    parser["Settings"] = settings
    with open(INI_FILE, "w") as f:
        parser.write(f)

def friday_events():
    """The friday_quran events one load of the schedule produces."""
    scheduler = service.AthanScheduler.__new__(service.AthanScheduler)
    scheduler.schedule = []
    scheduler.load_schedule()
    return [e for e in scheduler.schedule if e["type"] == "friday_quran"]

write_map()

print("1. it is scheduled on Fridays and on no other day")
write_ini()
events = friday_events()
chk("one event per Friday in the map", len(events), len(FRIDAYS))
chk("and they land on exactly those dates",
    sorted(e["datetime"].date() for e in events), FRIDAYS)

print("2. the default is an hour after the Jumu'ah prayer")
chk("Dhuhr 13:00 + 60 minutes", sorted({e["datetime"].strftime("%H:%M") for e in events}), ["14:00"])

print("3. before/after and the number of minutes both take effect")
write_ini(friday_quran_position="before", friday_quran_time="30")
chk("30 minutes before Dhuhr",
    sorted({e["datetime"].strftime("%H:%M") for e in friday_events()}), ["12:30"])
write_ini(friday_quran_position="after", friday_quran_time="90")
chk("90 minutes after Dhuhr",
    sorted({e["datetime"].strftime("%H:%M") for e in friday_events()}), ["14:30"])

print("4. it is never allowed to run into the Asr athan or start before sunrise")
# A single offset is applied to every Friday of the year, but the Dhuhr->Asr gap is nearly
# two hours shorter in December than in June. This is that winter Friday.
write_map(dhuhr="12:00", asr="14:00", sunrise="08:00")
write_ini(friday_quran_position="after", friday_quran_time="180")
chk("pulled back to a minute before Asr",
    sorted({e["datetime"].strftime("%H:%M") for e in friday_events()}), ["13:59"])
write_ini(friday_quran_position="before", friday_quran_time="300")
chk("pushed up to a minute after sunrise",
    sorted({e["datetime"].strftime("%H:%M") for e in friday_events()}), ["08:01"])
write_map()

print("5. the checkbox switches it off completely")
write_ini(enable_friday_quran="False")
chk("nothing is scheduled", friday_events(), [])
chk("and the event counts as skipped",
    "friday_quran" in service.load_skipped_events(), True)

print("6. a missing or nonsense setting falls back to an hour after")
write_ini(friday_quran_position="sideways", friday_quran_time="not a number")
chk("both values fall back", service.load_friday_quran_offset(), ("after", 60))
os.remove(INI_FILE)
chk("so does a config file that is not there yet",
    service.load_friday_quran_offset(), ("after", 60))
write_ini()

print("7. the audio it plays is its own selection, not the daily one")
write_ini(quran_audio_checked="daily.mp3", friday_quran_audio_checked="kahf.mp3")
chk("friday_quran reads friday_quran_audio_checked",
    service.get_audio_for_event("friday_quran"), "kahf.mp3")
chk("and the daily event is untouched",
    service.get_audio_for_event("quran"), "daily.mp3")

for path in (MAP_FILE, INI_FILE):
    if os.path.exists(path):
        os.remove(path)

# ---------------------------------------------------------------------------
# The player
# ---------------------------------------------------------------------------
print("8. the player knows where the Friday recitation lives")
AUDIO_DIR = os.path.join(SCHEDULER, "audio/friday_quran")
LOG = os.path.join(SCHEDULER, "logs/play_audio.log")
os.makedirs(AUDIO_DIR, exist_ok=True)
open(LOG, "w").close()

# An empty folder is what every device has the moment it takes this release, so it must be
# a quiet no-op rather than cvlc being handed an empty argument list.
run = subprocess.run(["/bin/bash", PLAY_AUDIO, "friday_quran", ""],
                     capture_output=True, text=True)
log = open(LOG, encoding="utf-8").read()
chk("an empty folder exits cleanly", run.returncode, 0)
chk("naming the folder it looked in", "audio/friday_quran" in log, True)
chk("and it is not mistaken for an unknown event", "ERROR: Unknown prayer" in log, False)

open(LOG, "w").close()
run = subprocess.run(["/bin/bash", PLAY_AUDIO, "friday_kahf", ""],
                     capture_output=True, text=True)
chk("a name that is not an event is still refused", run.returncode, 1)
chk("and friday_quran is offered as one that is",
    "friday_quran" in open(LOG, encoding="utf-8").read(), True)

# ---------------------------------------------------------------------------
# The Settings section
# ---------------------------------------------------------------------------
print("9. the Settings app writes what the scheduler reads")
saved_ini = open(SETTINGS_INI_FILE, encoding="utf-8").read()
sys.path.insert(0, os.path.dirname(APP))
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
gui = load(APP, "settings_app")
gui.arabic_info = lambda parent, title, text: None
gui.arabic_error = lambda parent, title, text: None
w = gui.ControlApp()

chk("the section defaults to an hour after", w.friday_quran_spin.value(), 60)
chk("and to after rather than before", w.selected_friday_quran_position(), "after")

w.friday_quran_chk.setChecked(True)
w.friday_quran_spin.setValue(45)
w.select_friday_quran_position("before")
chk("saving succeeds", w.save_settings(show_message=False), True)

written = configparser.ConfigParser()
written.read(SETTINGS_INI_FILE, encoding="utf-8")
saved = written["Settings"]
chk("enable_friday_quran written", saved.getboolean("enable_friday_quran"), True)
chk("friday_quran_time written", saved.get("friday_quran_time"), "45")
chk("friday_quran_position written", saved.get("friday_quran_position"), "before")

print("10. the label shows the coming Friday's own time")
friday = w.next_friday()
chk("the date it previews is a Friday", friday.weekday(), FRIDAY)
chk("today counts as Friday when it is one",
    (friday == date.today()) == (date.today().weekday() == FRIDAY), True)
row = w.load_prayer_row_for(friday)
expected = w.minutes_to_hhmm(
    w.clamp_friday_quran(w.time_to_minutes(row["Dhuhr"]) - 45, row))
chk("the label carries that time", expected in w.friday_quran_label_text(), True)

# The suite leaves the device's own settings as it found them.
open(SETTINGS_INI_FILE, "w", encoding="utf-8").write(saved_ini)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
