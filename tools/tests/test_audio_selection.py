"""An event plays only the files ticked for it, and one with none ticked is switched off
when Settings are saved - on the touch screen and on the website alike.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_audio_selection.py
"""
import os, sys, importlib.util, configparser, subprocess, tempfile, shutil

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
APPLICATIONS = os.path.join(SCHEDULER, "applications")
APP = os.path.join(APPLICATIONS, "desktop/scheduler_settings_gui/main.py")
PLAY_AUDIO = os.path.join(SCHEDULER, "config/scripts/play_audio.sh")
SETTINGS_INI_FILE = os.path.join(SCHEDULER, "config/config.ini")
DUHA_DIR = os.path.join(SCHEDULER, "audio/duha")

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


os.makedirs(DUHA_DIR, exist_ok=True)
for name in ("one.mp3", "two.mp3"):
    open(os.path.join(DUHA_DIR, name), "w").close()

print("1. the player plays the ticked files and nothing else")
bin_dir = tempfile.mkdtemp()
played = os.path.join(bin_dir, "played")
with open(os.path.join(bin_dir, "cvlc"), "w") as f:
    f.write(f'#!/bin/bash\nfor a in "$@"; do [[ "$a" == *.mp3 ]] && basename "$a"; done > {played}\n')
os.chmod(os.path.join(bin_dir, "cvlc"), 0o755)
env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

def play(event, ticked):
    if os.path.exists(played):
        os.remove(played)
    subprocess.run(["/bin/bash", PLAY_AUDIO, event, ticked], env=env, check=True)
    return open(played).read().split() if os.path.exists(played) else None

chk("one file ticked: only that one", play("duha", "two.mp3"), ["two.mp3"])
chk("none ticked: nothing, not the whole folder", play("duha", ""), None)
shutil.rmtree(bin_dir)

print("2. the website switches off an event saved with no file ticked")
sys.path.insert(0, APPLICATIONS)
sys.path.insert(0, os.path.join(APPLICATIONS, "services/web_ui"))
api = load(os.path.join(APPLICATIONS, "services/web_ui/api.py"), "web_api")
ini = os.path.join(tempfile.mkdtemp(), "config.ini")
shutil.copy(SETTINGS_INI_FILE, ini)
desktop = os.path.join(os.environ["HOME"], "Desktop")

def saved(key):
    c = configparser.ConfigParser(interpolation=None)
    c.read(ini, encoding="utf-8")
    return c["Settings"].get(key)

api.apply_submission(ini, SCHEDULER, desktop,
                     {"enable_duha_prayer": True, "duha_audio_checked": []})
chk("duha is switched off", saved("enable_duha_prayer"), "False")
api.apply_submission(ini, SCHEDULER, desktop,
                     {"enable_duha_prayer": True, "duha_audio_checked": ["one.mp3"]})
chk("and stays on with a file ticked", saved("enable_duha_prayer"), "True")
api.apply_submission(ini, SCHEDULER, desktop, {"duha_audio_checked": []})
chk("unticking the files alone switches it off too", saved("enable_duha_prayer"), "False")

print("3. the Settings app does the same, on the screen too")
sys.path.insert(0, os.path.dirname(APP))
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
app = QApplication(sys.argv)
gui = load(APP, "settings_app")
gui.arabic_info = lambda parent, title, text: None
gui.arabic_error = lambda parent, title, text: None
saved_ini = open(SETTINGS_INI_FILE, encoding="utf-8").read()
w = gui.ControlApp()

def tick(list_widget, names):
    for i in range(list_widget.count()):
        item = list_widget.item(i)
        item.setCheckState(Qt.Checked if item.text() in names else Qt.Unchecked)

w.duha_chk.setChecked(True)
tick(w.duha_audio_list, set())
fajr = w.prayer_checkboxes["enable_prayer_fajr"]
fajr.setChecked(True)
tick(w.prayer_audio_lists["fajr"], {"athan.mp3"})
chk("saving succeeds", w.save_settings(show_message=False), True)
written = configparser.ConfigParser(interpolation=None)
written.read(SETTINGS_INI_FILE, encoding="utf-8")
chk("duha with nothing ticked is saved off", written["Settings"].get("enable_duha_prayer"), "False")
chk("and its checkbox is unticked", w.duha_chk.isChecked(), False)
chk("fajr with a file ticked stays on",
    (written["Settings"].get("enable_prayer_fajr"), fajr.isChecked()), ("True", True))
with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
    f.write(saved_ini)
for name in ("one.mp3", "two.mp3"):
    os.remove(os.path.join(DUHA_DIR, name))

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
