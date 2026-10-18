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
from PyQt5.QtWidgets import QLabel
parts = [l for l in combo.parentWidget().findChildren(QLabel) if l.text() in ("رفع ملف", "حذف ملفات")]
chk("the two part headings carry no line that reads as a box edge",
    [("border-bottom" in l.styleSheet(), "border: none" in l.styleSheet()) for l in parts],
    [(False, True), (False, True)])
from PyQt5.QtWidgets import QFrame
sections = w.findChildren(QFrame, "section")
saved = w.findChild(QFrame, "savedBox")
instant = [f for f in sections if not saved.isAncestorOf(f)]
chk("the five sections that act at once are outlined dark grey",
    (len(instant), all(gui.INSTANT_SECTION_BORDER in f.styleSheet() for f in instant)), (5, True))
chk("the sections in the saved box keep the light outline",
    all(gui.SECTION_BORDER in f.styleSheet() for f in sections if saved.isAncestorOf(f)), True)
chk("and a section's style reaches no label inside it",
    [f.objectName() for f in w.findChildren(QFrame)
     if f.styleSheet().lstrip().startswith("QFrame {")], [])
chk("every section title wears the one darker grey",
    all(gui.TITLE_BACKGROUND in f.layout().itemAt(0).widget().styleSheet() for f in sections), True)
chk("the folders are offered by name",
    combo.itemText(combo.findData("duha")), "صلاة الضحى (duha)")
w.upload_audio_file()
chk("nothing is copied before a folder is chosen",
    (os.path.exists(os.path.join(DUHA_DIR, "new-duha.mp3")), len(errors)), (False, 1))
w.resize(800, 480); w.show(); app.processEvents()
def tap_point_covered(box):
    box.showPopup(); app.processEvents()
    popup = box.list_view
    covered = _QRect(popup.mapToGlobal(popup.rect().topLeft()), popup.size()).contains(
        box.mapToGlobal(box.rect().center()))
    box.hidePopup(); app.processEvents()
    return covered
from PyQt5.QtWidgets import QStyle, QStyleOptionComboBox, QScrollArea
from PyQt5.QtCore import QRect as _QRect
w.findChild(QScrollArea).ensureWidgetVisible(combo); app.processEvents()
for name, box in (("upload", combo), ("delete", w.remove_folder_combo)):
    w.findChild(QScrollArea).ensureWidgetVisible(box); app.processEvents()
    option = QStyleOptionComboBox(); box.initStyleOption(option)
    chk(f"the {name} folder list drops down instead of opening over its box",
        box.style().styleHint(QStyle.SH_ComboBox_Popup, option, box), 0)
    chk(f"so a tap's release on the {name} box chooses nothing", tap_point_covered(box), False)
from PyQt5.QtWidgets import QComboBox
over = [b for b in w.findChildren(QComboBox) if b.style().styleHint(
    QStyle.SH_ComboBox_Popup, QStyleOptionComboBox(), b)]
chk("and no list anywhere in Settings opens over its box", [b.currentText() for b in over], [])
chk("the app keeps no style sheet of its own, which would take the labels' font",
    app.styleSheet(), "")
chk("every list in Settings opens when the finger lifts",
    [b.currentText() for b in w.findChildren(QComboBox) if not isinstance(b, gui.TouchComboBox)], [])
from PyQt5.QtTest import QTest
w.findChild(QScrollArea).ensureWidgetVisible(combo); app.processEvents()
QTest.mousePress(combo, Qt.LeftButton, Qt.NoModifier, combo.rect().center())
QTest.qWait(700)
chk("a finger held on the folder box opens nothing yet", combo.list_view.isVisible(), False)
QTest.mouseRelease(combo, Qt.LeftButton, Qt.NoModifier, combo.rect().center())
QTest.qWait(50)
chk("lifting it opens the list, and it stays open", combo.list_view.isVisible(), True)
chk("drawn inside the Settings window, not in a window of its own, where the panel's taps "
    "landed beside the entries", (combo.list_view.window() is w, combo.list_view.isWindow()),
    (True, False))
chk("its scroll bar shown when needed, not switched off",
    combo.list_view.verticalScrollBarPolicy(), Qt.ScrollBarAsNeeded)
entry = combo.list_view.visualRect(combo.model().index(combo.findData("duha"), 0)).center()
QTest.mousePress(combo.list_view.viewport(), Qt.LeftButton, Qt.NoModifier, entry)
QTest.qWait(900)
QTest.mouseRelease(combo.list_view.viewport(), Qt.LeftButton, Qt.NoModifier, entry)
QTest.qWait(50)
chk("a held tap on an entry chooses it and closes the list",
    (combo.currentData(), combo.list_view.isVisible()), ("duha", False))
combo.setCurrentIndex(0)
w.paint_upload_button()
QTest.mouseClick(combo, Qt.LeftButton, Qt.NoModifier, combo.rect().center()); QTest.qWait(50)
chk("it opens again", combo.list_view.isVisible(), True)
pressed = []
w.upload_btn.pressed.connect(lambda: pressed.append(1))
w.findChild(QScrollArea).ensureWidgetVisible(w.upload_btn); app.processEvents()
if combo.list_view.isVisible():
    QTest.mouseClick(w.upload_btn, Qt.LeftButton, Qt.NoModifier, w.upload_btn.rect().center())
QTest.qWait(50)
chk("a tap beside it only closes it: nothing chosen, the button under the finger untouched",
    (combo.list_view.isVisible(), combo.currentIndex(), pressed), (False, 0, []))
QTest.mouseClick(combo, Qt.LeftButton, Qt.NoModifier, combo.rect().center()); QTest.qWait(50)
QTest.mouseClick(combo, Qt.LeftButton, Qt.NoModifier, combo.rect().center()); QTest.qWait(50)
chk("a tap on its own box closes it and does not open it again", combo.list_view.isVisible(), False)
QTest.mouseClick(w.upload_btn, Qt.LeftButton, Qt.NoModifier, w.upload_btn.rect().center())
chk("and taps after that reach what they land on", pressed, [1])
w.upload_btn.pressed.disconnect()

from PyQt5.QtGui import QMouseEvent
from PyQt5.QtCore import QEvent as _QEvent, QPoint
def finger(kind, widget, point, held=Qt.LeftButton):
    app.sendEvent(widget, QMouseEvent(kind, QPoint(point), widget.mapToGlobal(QPoint(point)),
                                      Qt.LeftButton, held, Qt.NoModifier))
from PyQt5.QtWidgets import QWidget
long_page = QWidget(); long_page.resize(800, 480)
long_list = gui.TouchComboBox(long_page); long_list.setStyleSheet(gui.COMBO_STYLE)
long_list.addItems([f"entry {i}" for i in range(30)]); long_list.setGeometry(400, 20, 300, 45)
long_page.show(); app.processEvents()
QTest.mouseClick(long_list, Qt.LeftButton, Qt.NoModifier, long_list.rect().center()); QTest.qWait(50)
view = long_list.list_view.viewport()
start = view.rect().center() + QPoint(0, view.height() // 3)
finger(_QEvent.MouseButtonPress, view, start); QTest.qWait(30)
for step in range(1, 13):
    finger(_QEvent.MouseMove, view, start - QPoint(0, step * 15)); QTest.qWait(25)
finger(_QEvent.MouseButtonRelease, view, start - QPoint(0, 180), Qt.NoButton); QTest.qWait(1500)
chk("a swipe up an open list too long for the screen scrolls it, chooses nothing, stays open",
    (long_list.list_view.verticalScrollBar().value() > 0, long_list.currentIndex(),
     long_list.list_view.isVisible()), (True, 0, True))
below = long_list.list_view.indexAt(view.rect().center())
chk("bringing entries below into reach", below.row() > long_list.maxVisibleItems() // 2, True)
chk("with a scroll bar to show there are more",
    long_list.list_view.verticalScrollBar().isVisible(), True)
QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier, view.rect().center()); QTest.qWait(300)
chk("and a tap that stays put chooses the one under it",
    (long_list.currentIndex(), long_list.list_view.isVisible()), (below.row(), False))
long_page.close()
w.hide()
chk("the upload button is grey before a folder is chosen",
    gui.AUDIO_BUTTON_IDLE[0] in w.upload_btn.styleSheet(), True)
combo.setCurrentIndex(combo.findData("duha"))
chk("and green once one is", gui.AUDIO_UPLOAD_READY[0] in w.upload_btn.styleSheet(), True)
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
chk("no list before a folder is chosen, but the delete button is there, grey, like upload's",
    (w.remove_list.isHidden(), w.remove_list.count(), w.remove_btn.isHidden(),
     gui.AUDIO_BUTTON_IDLE[0] in w.remove_btn.styleSheet()), (True, 0, False, True))
combo.setCurrentIndex(combo.findData("duha"))
chk("the list appears once one is", w.remove_list.isHidden(), False)
chk("the delete button is grey with nothing ticked",
    gui.AUDIO_BUTTON_IDLE[0] in w.remove_btn.styleSheet(), True)
w.remove_list.item(0).setCheckState(Qt.Checked)
chk("red once a file is ticked", gui.AUDIO_DELETE_READY[0] in w.remove_btn.styleSheet(), True)
w.remove_list.item(0).setCheckState(Qt.Unchecked)
chk("and grey again when it is unticked",
    gui.AUDIO_BUTTON_IDLE[0] in w.remove_btn.styleSheet(), True)
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
chk("with the button grey again", gui.AUDIO_BUTTON_IDLE[0] in w.remove_btn.styleSheet(), True)
written = configparser.ConfigParser(interpolation=None)
written.read(SETTINGS_INI_FILE, encoding="utf-8")
chk("unticked in config.ini, and the event switched off there",
    (written["Settings"].get("duha_audio_checked"), written["Settings"].get("enable_duha_prayer")),
    ("", "False"))
chk("and on the screen", (w.duha_chk.isChecked(), w.config["Settings"]["duha_audio_checked"]),
    (False, ""))
chk("the schedule is rebuilt for it", applied, [True])
chk("the owner is told", "فتم إيقافه" in (infos[-1] if infos else ""), True)
os.remove(os.path.join(DUHA_DIR, "new-duha.mp3"))
w.fill_remove_list()
chk("an empty folder says so", [w.remove_list.item(i).text() for i in range(w.remove_list.count())],
    ["لا توجد ملفات صوتية في هذا المجلد"])
combo.setCurrentIndex(0)
chk("and choosing no folder hides the list again, not the button",
    (w.remove_list.isHidden(), w.remove_btn.isHidden()), (True, False))
open(os.path.join(DUHA_DIR, "new-duha.mp3"), "w").close()
combo.setCurrentIndex(combo.findData("duha"))
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

print("6. a finger swipes the list of files to delete without ticking any")
for i in range(20):
    open(os.path.join(DUHA_DIR, f"recitation-{i:02}.mp3"), "w").close()
w.resize(800, 480); w.show(); app.processEvents()
w.remove_folder_combo.setCurrentIndex(w.remove_folder_combo.findData("duha"))
w.fill_remove_list()
w.findChild(QScrollArea).ensureWidgetVisible(w.remove_list); app.processEvents()
files = w.remove_list.viewport()
start = files.rect().center() + QPoint(0, files.height() // 3)
finger(_QEvent.MouseButtonPress, files, start); QTest.qWait(30)
for step in range(1, 13):
    finger(_QEvent.MouseMove, files, start - QPoint(0, step * 12)); QTest.qWait(25)
finger(_QEvent.MouseButtonRelease, files, start - QPoint(0, 144), Qt.NoButton); QTest.qWait(1500)
ticked = [w.remove_list.item(i).text() for i in range(w.remove_list.count())
          if w.remove_list.item(i).checkState() == Qt.Checked]
chk("the swipe scrolls the files and ticks none",
    (w.remove_list.verticalScrollBar().value() > 0, ticked), (True, []))
under = w.remove_list.indexAt(files.rect().center())
QTest.mouseClick(files, Qt.LeftButton, Qt.NoModifier, files.rect().center()); QTest.qWait(300)
chk("a tap that stays put still reaches the file under it", w.remove_list.currentRow(), under.row())

print("7. --debug writes down every tap, what it landed on and what came of it")
debug_path = os.path.join(tempfile.mkdtemp(), "settings_debug.log")
gui.start_debug_log(app, debug_path)
w.watch_for_debug()
upload = w.upload_folder_combo
upload.setCurrentIndex(0)
w.findChild(QScrollArea).ensureWidgetVisible(upload); app.processEvents()
QTest.mouseClick(upload, Qt.LeftButton, Qt.NoModifier, upload.rect().center()); QTest.qWait(50)
entry = upload.list_view.visualRect(upload.model().index(upload.findData("duha"), 0)).center()
QTest.mouseClick(upload.list_view.viewport(), Qt.LeftButton, Qt.NoModifier, entry); QTest.qWait(300)
logged = open(debug_path, encoding="utf-8").read()
for needle in ("Settings started in debug mode", "release at", "on menu upload_folder_combo",
               "menu upload_folder_combo opens its list", "on open list upload_folder_combo entry",
               "'صلاة الضحى (duha)'", "menu upload_folder_combo chose 'صلاة الضحى (duha)'",
               "menu upload_folder_combo closes its list"):
    chk(f"the log has: {needle}", needle in logged, True)
chk("each tap once, on the widget it hit, not again on every parent it passed up to",
    len([line for line in logged.splitlines() if " release at " in line]), 2)
w.remove_list.item(0).setCheckState(Qt.Checked)
chk("and a tick in a list", "list remove_list ticked 'recitation-00.mp3'"
    in open(debug_path, encoding="utf-8").read(), True)
gui.DEBUG_LOG.close(); gui.DEBUG_LOG = None
app.removeEventFilter(app.debug_filter)
for name in os.listdir(DUHA_DIR):
    os.remove(os.path.join(DUHA_DIR, name))

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
