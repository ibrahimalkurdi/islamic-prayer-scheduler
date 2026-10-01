"""Athkar Elsabah at a fixed time, or a number of minutes after Fajr: the schedule that
places it, and the Settings section that chooses between the two.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_athkar_elsabah.py

01_add_fields.py needs pandas, which the device has and a desktop may not. Point
ADD_FIELDS_PYTHON at an interpreter that has it to run the schedule half here.
"""
import os, sys, csv, shutil, importlib.util, configparser, subprocess, tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
ADD_FIELDS = os.path.join(SCHEDULER, "config/scripts/01_add_fields.py")
APP = os.path.join(SCHEDULER, "applications/desktop/scheduler_settings_gui/main.py")
SETTINGS_INI_FILE = os.path.join(SCHEDULER, "config/config.ini")
ADD_FIELDS_PYTHON = os.environ.get("ADD_FIELDS_PYTHON", sys.executable)

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------
# Three days: an ordinary one, one whose Fajr is after 9:45 and one whose Dhuhr is before
# it - the two a fixed time has to be moved inside on.
ROWS = [
    {"Month": 1, "Day": 1, "Fajr": "05:00", "Sunrise": "07:00", "Dhuhr": "12:30",
     "Asr": "15:00", "Maghrib": "17:00", "Isha": "18:30"},
    {"Month": 1, "Day": 2, "Fajr": "10:00", "Sunrise": "11:00", "Dhuhr": "12:30",
     "Asr": "15:00", "Maghrib": "17:00", "Isha": "18:30"},
    {"Month": 1, "Day": 3, "Fajr": "05:00", "Sunrise": "07:00", "Dhuhr": "09:30",
     "Asr": "15:00", "Maghrib": "17:00", "Isha": "18:30"},
]


def athkar_column(settings):
    """Athkar_elsabah for each of ROWS, as 01_add_fields.py writes it given these
    settings (None: no config.ini at all)."""
    home = tempfile.mkdtemp(dir=HERE)
    try:
        config_dir = os.path.join(home, "Desktop/scheduler/config")
        os.makedirs(config_dir)
        with open(os.path.join(config_dir, "input-prayers-time.csv"), "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(ROWS[0]))
            writer.writeheader()
            writer.writerows(ROWS)
        if settings is not None:
            parser = configparser.ConfigParser()
            parser["Settings"] = settings
            with open(os.path.join(config_dir, "config.ini"), "w") as f:
                parser.write(f)
        subprocess.run([ADD_FIELDS_PYTHON, ADD_FIELDS], check=True, capture_output=True,
                       env=dict(os.environ, HOME=home))
        with open(os.path.join(config_dir, "prayer_times.csv"), newline="") as f:
            return [row["Athkar_elsabah"] for row in csv.DictReader(f)]
    finally:
        shutil.rmtree(home)


has_pandas = subprocess.run([ADD_FIELDS_PYTHON, "-c", "import pandas"],
                            capture_output=True).returncode == 0
chk(f"{ADD_FIELDS_PYTHON} can run 01_add_fields.py (has pandas; see ADD_FIELDS_PYTHON)",
    has_pandas, True)

if has_pandas:
    print("1. a device that has never chosen gets a fixed 9:45")
    chk("a config.ini from before the choice", athkar_column({"athkar_elsabah_time": "240"}),
        ["09:45", "10:01", "09:29"])
    chk("and no config.ini at all", athkar_column(None), ["09:45", "10:01", "09:29"])

    print("2. a fixed time is the same every day it fits, and moved inside where it does not")
    chk("10:15 every day, a minute after Fajr, a minute before Dhuhr",
        athkar_column({"athkar_elsabah_mode": "clock", "athkar_elsabah_clock": "10:15"}),
        ["10:15", "10:15", "09:29"])
    chk("a clock that is not one falls back to 9:45",
        athkar_column({"athkar_elsabah_mode": "clock", "athkar_elsabah_clock": "late"}),
        ["09:45", "10:01", "09:29"])

    print("3. minutes after Fajr still work as they did")
    chk("Fajr + 60, held a minute before Dhuhr",
        athkar_column({"athkar_elsabah_mode": "after_fajr", "athkar_elsabah_time": "60",
                       "athkar_elsabah_clock": "10:15"}),
        ["06:00", "11:00", "06:00"])
    chk("an unknown mode is read as the default",
        athkar_column({"athkar_elsabah_mode": "sometimes", "athkar_elsabah_time": "60"}),
        ["09:45", "10:01", "09:29"])


# ---------------------------------------------------------------------------
# The Settings section
# ---------------------------------------------------------------------------
print("4. the Settings app offers the choice, a fixed 9:45 first")
saved_ini = open(SETTINGS_INI_FILE, encoding="utf-8").read()
parser = configparser.ConfigParser()
parser.read_string(saved_ini)
for key in ("athkar_elsabah_mode", "athkar_elsabah_clock"):
    parser.remove_option("Settings", key)
with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
    parser.write(f)

sys.path.insert(0, os.path.dirname(APP))
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
spec = importlib.util.spec_from_file_location("settings_app", APP)
gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
warnings = []
gui.arabic_info = lambda parent, title, text: None
gui.arabic_error = lambda parent, title, text: None
gui.arabic_warning = lambda parent, title, text: warnings.append(text)

try:
    w = gui.ControlApp()
    w.show()
    chk("the mode defaults to a fixed time", w.selected_athkar_elsabah_mode(), "clock")
    chk("at 9:45", (w.athkar_elsabah_hour_spin.value(), w.athkar_elsabah_min_spin.value()),
        (9, 45))
    chk("the hour and minute are shown", (w.athkar_elsabah_hour_spin.isVisible(),
                                          w.athkar_elsabah_min_spin.isVisible()), (True, True))
    chk("and the minutes after Fajr are not", w.athkar_elsabah_spin.isVisible(), False)
    chk("the label previews 9:45",
        "9:45 AM" in w.athkar_elsabah_time_label.text(), True)

    print("5. choosing minutes after Fajr swaps what is shown")
    w.select_athkar_elsabah_mode("after_fajr")
    chk("the minutes are shown", w.athkar_elsabah_spin.isVisible(), True)
    chk("and the hour and minute are not", (w.athkar_elsabah_hour_spin.isVisible(),
                                            w.athkar_elsabah_min_spin.isVisible()),
        (False, False))
    fajr = w.get_today_prayer_times()["fajr"]
    chk("the label previews Fajr plus the minutes",
        w.minutes_to_clock(fajr + w.athkar_elsabah_spin.value())
        in w.athkar_elsabah_time_label.text(), True)

    print("6. a fixed time past today's Dhuhr is refused, in the shared words")
    w.select_athkar_elsabah_mode("clock")
    w.athkar_elsabah_hour_spin.setValue(23)
    chk("it is refused", w.athkar_elsabah_conflicts_with_dhuhr(), True)
    message = warnings[-1] if warnings else ""
    chk("naming Fajr and Dhuhr", "صلاة الفجر" in message and "صلاة الظهر" in message, True)

    print("7. saving writes the choice, and keeps the minutes for later")
    w.athkar_elsabah_hour_spin.setValue(10)
    w.athkar_elsabah_min_spin.setValue(5)
    chk("10:05 is accepted", w.athkar_elsabah_conflicts_with_dhuhr(), False)
    chk("saving succeeds", w.save_settings(show_message=False), True)
    written = configparser.ConfigParser()
    written.read(SETTINGS_INI_FILE, encoding="utf-8")
    chk("athkar_elsabah_mode written", written["Settings"].get("athkar_elsabah_mode"), "clock")
    chk("athkar_elsabah_clock written", written["Settings"].get("athkar_elsabah_clock"), "10:05")
    chk("athkar_elsabah_time kept", written["Settings"].get("athkar_elsabah_time"),
        str(w.athkar_elsabah_spin.value()))

    print("8. reopening the app reads it back")
    w2 = gui.ControlApp()
    chk("mode", w2.selected_athkar_elsabah_mode(), "clock")
    chk("time", (w2.athkar_elsabah_hour_spin.value(), w2.athkar_elsabah_min_spin.value()),
        (10, 5))
finally:
    with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
        f.write(saved_ini)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
