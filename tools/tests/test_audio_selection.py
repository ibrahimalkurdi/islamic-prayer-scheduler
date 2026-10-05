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

print("4. a recitation picked on the device is copied into the folder chosen for it")
source_dir = tempfile.mkdtemp()
source = os.path.join(source_dir, "new-duha.mp3")
with open(source, "wb") as f:
    f.write(b"ID3" + b"\0" * 4000)
gui.QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (source, ""))
errors = []
gui.arabic_error = lambda parent, title, text: errors.append(text)
combo = w.upload_folder_combo
chk("the folders are offered by name",
    combo.itemText(combo.findData("duha")), "صلاة الضحى (duha)")
w.upload_audio_file()
chk("nothing is copied before a folder is chosen",
    (os.path.exists(os.path.join(DUHA_DIR, "new-duha.mp3")), len(errors)), (False, 1))
combo.setCurrentIndex(combo.findData("duha"))
w.upload_audio_file()
w.upload_worker.wait()
app.processEvents()
chk("it is copied", open(os.path.join(DUHA_DIR, "new-duha.mp3"), "rb").read(),
    open(source, "rb").read())
listed = {w.duha_audio_list.item(i).text(): w.duha_audio_list.item(i).checkState()
          for i in range(w.duha_audio_list.count())}
chk("and listed at once, unticked", listed.get("new-duha.mp3"), Qt.Unchecked)
chk("in the list's own order", [w.duha_audio_list.item(i).text()
                                for i in range(w.duha_audio_list.count())],
    ["new-duha.mp3", "one.mp3", "two.mp3"])
chk("the button is back", (w.upload_btn.isEnabled(), w.upload_btn.text()),
    (True, "اختيار الملف الصوتي ورفعه"))
asked = []
gui.arabic_confirm = lambda parent, title, text: asked.append(text) or False
w.upload_audio_file()
chk("the same name again is asked about, and a no copies nothing",
    (len(asked), w.duha_audio_list.count()), (1, 3))
if os.environ.get("UPLOAD_SAMPLE"):
    w.resize(800, 1200)
    w.show()
    app.processEvents()
    w.upload_btn.parentWidget().grab().save(os.environ["UPLOAD_SAMPLE"])
shutil.rmtree(source_dir)

print("5. recitations are deleted from a folder, asked about first, and unticked")
with open(SETTINGS_INI_FILE, encoding="utf-8") as f:
    saved_ini = f.read()
w.duha_chk.setChecked(True)
tick(w.duha_audio_list, {"one.mp3"})
chk("saved with one ticked", w.save_settings(show_message=False), True)
combo = w.remove_folder_combo
chk("nothing listed before a folder is chosen", w.remove_list.item(0).flags(), Qt.NoItemFlags)
combo.setCurrentIndex(combo.findData("duha"))
chk("the folder's files are listed to tick",
    [w.remove_list.item(i).text() for i in range(w.remove_list.count())],
    ["new-duha.mp3", "one.mp3", "two.mp3"])
errors.clear()
w.delete_audio_files()
chk("none ticked deletes nothing", (len(errors), len(os.listdir(DUHA_DIR))), (1, 3))
tick(w.remove_list, {"one.mp3", "two.mp3"})
asked.clear()
w.delete_audio_files()
question = asked[0] if asked else ""
chk("a no deletes nothing", (len(asked), sorted(os.listdir(DUHA_DIR))),
    (1, ["new-duha.mp3", "one.mp3", "two.mp3"]))
chk("the question names the files and says the event stops",
    all(n in question for n in ("one.mp3", "two.mp3", "صلاة الضحى", "فسيتم إيقافه")), True)
gui.arabic_confirm = lambda parent, title, text: True
infos = []
gui.arabic_info = lambda parent, title, text: infos.append(text)
applied = []
gui.ApplySettingsWorker.start = lambda self: applied.append(True)
w.delete_audio_files()
chk("a yes deletes them", sorted(os.listdir(DUHA_DIR)), ["new-duha.mp3"])
chk("gone from the event's list too",
    [w.duha_audio_list.item(i).text() for i in range(w.duha_audio_list.count())],
    ["new-duha.mp3"])
chk("and from the delete list",
    [w.remove_list.item(i).text() for i in range(w.remove_list.count())], ["new-duha.mp3"])
written = configparser.ConfigParser(interpolation=None)
written.read(SETTINGS_INI_FILE, encoding="utf-8")
chk("unticked in config.ini, and the event switched off there",
    (written["Settings"].get("duha_audio_checked"), written["Settings"].get("enable_duha_prayer")),
    ("", "False"))
chk("and on the screen", (w.duha_chk.isChecked(), w.config["Settings"]["duha_audio_checked"]),
    (False, ""))
chk("the schedule is rebuilt for it", applied, [True])
chk("the owner is told", "فتم إيقافه" in (infos[-1] if infos else ""), True)
if os.environ.get("DELETE_SAMPLE"):
    combo.setCurrentIndex(combo.findData("duha"))
    for name in ("one.mp3", "two.mp3"):
        open(os.path.join(DUHA_DIR, name), "w").close()
    w.fill_remove_list()
    tick(w.remove_list, {"two.mp3"})
    w.resize(800, 1200)
    w.show()
    app.processEvents()
    w.remove_btn.parentWidget().grab().save(os.environ["DELETE_SAMPLE"])
with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
    f.write(saved_ini)
for name in os.listdir(DUHA_DIR):
    os.remove(os.path.join(DUHA_DIR, name))

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
