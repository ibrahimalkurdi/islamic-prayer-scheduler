"""The shipped default settings: what a device falls back to for a key its config.ini
lacks, and what «إعادة ضبط الإعدادات» puts back.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_default_settings.py
"""
import os, sys, shutil, importlib.util, configparser

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
APP = os.path.join(SCHEDULER, "applications/desktop/scheduler_settings_gui/main.py")
SETTINGS_INI_FILE = os.path.join(SCHEDULER, "config/config.ini")
DEFAULTS_FILE = os.path.join(SCHEDULER, "config/default-config.ini")
AUDIO = os.path.join(SCHEDULER, "audio")

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


def read_settings(path):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return parser["Settings"]


print("1. the release carries the defaults")
chk("default-config.ini is in the tree", os.path.isfile(DEFAULTS_FILE), True)
defaults = read_settings(DEFAULTS_FILE)
chk("the Quran at 7:00", defaults.get("listen_to_quran"), "07:00")
chk("Athkar Elsabah at a fixed 9:45",
    (defaults.get("athkar_elsabah_mode"), defaults.get("athkar_elsabah_clock")),
    ("clock", "09:45"))
chk("no device's own prayer-times file", "prayer_csv_source_label" in defaults, False)

saved_ini = open(SETTINGS_INI_FILE, encoding="utf-8").read()
seeded = []
def seed(event, *names):
    folder = os.path.join(AUDIO, event)
    os.makedirs(folder, exist_ok=True)
    for name in names:
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            open(path, "w").close()
            seeded.append(path)

# Athkar Elsabah has the file the defaults name, beside one they do not. Duha has only
# files the defaults do not name.
DEFAULT_ATHKAR = defaults.get("athkar_elsabah_audio_checked")
seed("athkar_elsabah", DEFAULT_ATHKAR, "another-athkar.mp3")
seed("duha", "duha-one.mp3", "duha-two.mp3")

# Someone's own settings, far from the defaults, and a prayer-times file they picked.
parser = configparser.ConfigParser(interpolation=None)
parser.read_string(saved_ini)
s = parser["Settings"]
s["listen_to_quran"] = "05:15"
s["athkar_elsabah_mode"] = "after_fajr"
s["athkar_elsabah_time"] = "90"
s["enable_daylight_saving"] = "False"
s["enable_athkar_elmasa"] = "False"
s["prayer_csv_source_label"] = "/somewhere/برلين.csv"
s["athkar_elsabah_audio_checked"] = "another-athkar.mp3"
with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
    parser.write(f)

sys.path.insert(0, os.path.dirname(APP))
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
spec = importlib.util.spec_from_file_location("settings_app", APP)
gui = importlib.util.module_from_spec(spec); spec.loader.exec_module(gui)
gui.arabic_info = lambda parent, title, text: None
gui.arabic_error = lambda parent, title, text: print("    error:", text)
gui.arabic_confirm = lambda parent, title, text: True
# The reset runs init.sh, which is not for a fixture: a stand-in records that it ran.
INIT_MARKER = os.path.join(HERE, "init-ran")
INIT_STUB = os.path.join(HERE, "init-stub.sh")
with open(INIT_STUB, "w") as f:
    f.write(f"#!/bin/bash\necho \"$SCHEDULER_INIT_APPLY_SETTINGS\" > '{INIT_MARKER}'\n")
if os.path.exists(INIT_MARKER):
    os.remove(INIT_MARKER)
gui.INIT_SCRIPT_FILE = INIT_STUB

try:
    print("2. a key a device's config.ini lacks comes from the defaults")
    parser.remove_option("Settings", "athkar_elsabah_clock")
    with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
        parser.write(f)
    w = gui.ControlApp()
    chk("the Athkar clock it never saved is 9:45",
        (w.athkar_elsabah_hour_spin.value(), w.athkar_elsabah_min_spin.value()), (9, 45))
    chk("while what it did save is kept", w.selected_athkar_elsabah_mode(), "after_fajr")

    print("3. the reset puts the shipped defaults back")
    w.reset_settings()
    written = read_settings(SETTINGS_INI_FILE)
    for key in ("listen_to_quran", "athkar_elsabah_mode", "athkar_elsabah_clock",
                "athkar_elsabah_time", "enable_athkar_elmasa", "friday_quran_position"):
        chk(f"{key} is the default", written.get(key), defaults.get(key))
    chk("the retired daylight-saving choice is gone, not reset",
        [k for k in ("enable_daylight_saving", "daylight_saving_timezone") if k in written], [])
    for _ in range(50):
        if os.path.exists(INIT_MARKER):
            break
        app.processEvents(); __import__("time").sleep(0.1)
    chk("init.sh is still run after it", os.path.exists(INIT_MARKER), True)
    chk("told to apply the reset settings, though the device was set up before",
        open(INIT_MARKER).read().strip() if os.path.exists(INIT_MARKER) else None, "1")

    print("4. and shows them")
    chk("Quran 7:00", (w.cron_hour_spin.value(), w.cron_min_spin.value()), (7, 0))
    chk("Athkar Elsabah a fixed 9:45",
        (w.selected_athkar_elsabah_mode(), w.athkar_elsabah_hour_spin.value(),
         w.athkar_elsabah_min_spin.value()), ("clock", 9, 45))
    chk("with no daylight-saving choice on screen", hasattr(w, "dst_chk"), False)
    chk("Athkar Elmasa back on", w.athkar_elmasa_chk.isChecked(), True)

    print("5. it does not forget the prayer-times file")
    chk("the source it was picked from is kept",
        written.get("prayer_csv_source_label"), "/somewhere/برلين.csv")

    print("6. audio: the default files where the device has them, otherwise every file")
    chk("Athkar Elsabah ticks the default recitation only",
        written.get("athkar_elsabah_audio_checked"), DEFAULT_ATHKAR)
    chk("Duha, with none of the default files, ticks all it has",
        sorted(written.get("duha_audio_checked").split(",")), ["duha-one.mp3", "duha-two.mp3"])
finally:
    with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
        f.write(saved_ini)
    for path in seeded + [INIT_STUB, INIT_MARKER]:
        if os.path.exists(path):
            os.remove(path)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
