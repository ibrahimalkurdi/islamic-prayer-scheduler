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

print("8. beside the daily Quran's time: when its ticked files finish")
import struct
QURAN_DIR = os.path.join(SCHEDULER, "audio/quran")
made_quran_dir = not os.path.isdir(QURAN_DIR)
os.makedirs(QURAN_DIR, exist_ok=True)
def recitation(name, seconds):
    """A tiny MP3 whose Xing header names enough 1152-sample frames for `seconds`."""
    header = b"\xff\xfb\x90\x00"
    first = header + bytes(32) + b"Xing" + struct.pack(">II", 1, round(seconds * 44100 / 1152))
    with open(os.path.join(QURAN_DIR, name), "wb") as handle:
        handle.write(first + bytes(417 - len(first)) + (header + bytes(413)) * 3)
    w.add_audio_list_item(QURAN_DIR, name)
recitation("zz-baqara.mp3", 90 * 60)
recitation("zz-kahf.mp3", 60 * 60)
with open(os.path.join(QURAN_DIR, "zz-broken.mp3"), "w") as handle:
    handle.write("not audio")
w.add_audio_list_item(QURAN_DIR, "zz-broken.mp3")
plain = lambda: w.quran_end_label.text().replace(gui.LTR_ISOLATE, "").replace(gui.POP_ISOLATE, "")
tick(w.quran_audio_list, set())
chk("nothing ticked: it asks for the files", plain(), "اختر السور أدناه لمعرفة وقت الانتهاء")
w.cron_hour_spin.setValue(7); w.cron_min_spin.setValue(0)
tick(w.quran_audio_list, {"zz-baqara.mp3", "zz-kahf.mp3"})
chk("two and a half hours from 7:00 runs until 9:30", plain(), "حتى 9:30 AM · المدة 2:30 ساعة")
w.cron_hour_spin.setValue(23)
chk("it follows the time as it changes, past midnight too", plain(),
    "حتى 1:30 AM · المدة 2:30 ساعة")
tick(w.quran_audio_list, {"zz-kahf.mp3"})
chk("and the ticks", plain(), "حتى 12:00 AM · المدة 1:00 ساعة")
tick(w.quran_audio_list, {"zz-kahf.mp3", "zz-broken.mp3"})
chk("a file it cannot read is said, not counted", plain(),
    "حتى 12:00 AM · المدة 1:00 ساعة (تعذّرت قراءة مدة بعض الملفات)")
chk("a grey box", "background-color: #e4e4e4" in w.quran_end_label.styleSheet(), True)
from PyQt5.QtWidgets import QFormLayout
form = next(f for f in w.cron_frame.layout().findChildren(QFormLayout)
            if f.indexOf(w.cron_min_spin) >= 0)
chk("in the rows of the time it is chosen beside",
    [type(form.itemAt(r, form.FieldRole).widget()).__name__ for r in range(form.rowCount())
     if form.itemAt(r, form.FieldRole) is not None][-3:], ["QSpinBox", "QSpinBox", "QLabel"])
recitation("zz-short.mp3", 20 * 60)
tick(w.quran_audio_list, {"zz-short.mp3"})
w.cron_hour_spin.setValue(6); w.cron_min_spin.setValue(30)
chk("under an hour, in minutes", plain(), "حتى 6:50 AM · المدة 20 دقيقة")
chk("and under a minute said as such", gui.duration_text(25), "أقل من دقيقة")
w.forget_deleted_audio("quran", {"zz-short.mp3"}, False)
chk("a ticked file deleted is taken out of it at once", plain(),
    "اختر السور أدناه لمعرفة وقت الانتهاء")
for name in ("zz-baqara.mp3", "zz-kahf.mp3", "zz-broken.mp3", "zz-short.mp3"):
    os.remove(os.path.join(QURAN_DIR, name))

print("9. every event shows when it ends, and running into another is warned of")
ATHKAR_DIR = os.path.join(SCHEDULER, "audio/athkar_elsabah")
made_athkar_dir = not os.path.isdir(ATHKAR_DIR)
os.makedirs(ATHKAR_DIR, exist_ok=True)
os.makedirs(QURAN_DIR, exist_ok=True)
def timed(directory, name, seconds):
    header = b"\xff\xfb\x90\x00"
    first = header + bytes(32) + b"Xing" + struct.pack(">II", 1, round(seconds * 44100 / 1152))
    with open(os.path.join(directory, name), "wb") as handle:
        handle.write(first + bytes(417 - len(first)) + (header + bytes(413)) * 3)
    w.add_audio_list_item(directory, name)
timed(ATHKAR_DIR, "zz-athkar.mp3", 20 * 60)
timed(QURAN_DIR, "zz-long.mp3", 3 * 3600)
warned = []
gui.arabic_warning = lambda parent, title, text: warned.append(text)
for chk_box in [*w.prayer_checkboxes.values(), w.tahajjud_chk, w.duha_chk,
                w.athkar_elmasa_chk, w.friday_quran_chk]:
    chk_box.setChecked(False)
end_text = lambda event: w.end_labels[event].text().replace(gui.LTR_ISOLATE, "").replace(
    gui.POP_ISOLATE, "")
chk("a box under every event, the athans and Surat Al-Kahf too",
    sorted(w.end_labels), sorted(["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha",
                                  "tahajjud", "duha", "athkar_elsabah", "athkar_elmasa",
                                  "quran", "friday_quran"]))
w.resize(800, 480); w.show(); app.processEvents()
def reads_right_to_left(event):
    box = w.end_labels[event]
    title = next(l for l in box.parentWidget().findChildren(type(box)) if l is not box)
    return title.geometry().x() > box.geometry().x() and box.geometry().right() > box.parentWidget().width() // 3
chk("each row reads right to left: its title on the right, the box beside it",
    [e for e in ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha", "tahajjud", "duha",
                 "athkar_elsabah", "athkar_elmasa", "friday_quran") if not reads_right_to_left(e)], [])
starts = {"fajr": w.prayer_time_labels["fajr"], "duha": w.duha_time_label,
          "athkar_elmasa": w.athkar_elmasa_time_label}
chk("each start is in the same grey box as its end, under a title of the same size",
    [(e, label.styleSheet() == gui.QURAN_END_STYLE,
      next(l for l in label.parentWidget().findChildren(type(label)) if l is not label).text())
     for e, label in starts.items()],
    [(e, True, gui.START_LABEL_TEXT) for e in starts])
chk("and holds the time alone",
    w.duha_time_label.text().replace(gui.LTR_ISOLATE, "").replace(gui.POP_ISOLATE, "")[-3:], " AM")
chk("all of them the same grey box",
    {label.styleSheet() for label in w.end_labels.values()}, {gui.QURAN_END_STYLE})
tick(w.prayer_audio_lists["fajr"], set())
chk("an athan with nothing ticked asks for its files", end_text("fajr"),
    "اختر الملفات أدناه لمعرفة وقت الانتهاء")
w.athkar_elsabah_chk.setChecked(True)
w.select_athkar_elsabah_mode(gui.ATHKAR_ELSABAH_MODE_CLOCK)
w.athkar_elsabah_hour_spin.setValue(9); w.athkar_elsabah_min_spin.setValue(45)
tick(w.athkar_elsabah_audio_list, {"zz-athkar.mp3"})
chk("Athkar Elsabah at 9:45 with twenty minutes of files ends at 10:05",
    end_text("athkar_elsabah"), "حتى 10:05 AM · المدة 20 دقيقة")
chk("at a fixed time it has no start line, like the daily Quran",
    w.athkar_elsabah_time_label.isHidden(), True)
w.select_athkar_elsabah_mode(gui.ATHKAR_ELSABAH_MODE_AFTER_FAJR)
chk("worked out from Fajr, it shows when it starts", w.athkar_elsabah_time_label.isHidden(), False)
w.select_athkar_elsabah_mode(gui.ATHKAR_ELSABAH_MODE_CLOCK)
fajr_today = w.get_today_prayer_times()["fajr"]
w.athkar_elsabah_hour_spin.setValue((fajr_today - 60) // 60)
chk("unless the time had to be moved, which that line says",
    (w.athkar_elsabah_time_label.isHidden(), "تم تعديله" in w.athkar_elsabah_time_label.text()),
    (False, True))
w.athkar_elsabah_hour_spin.setValue(9)
chk("and gone again once it fits", w.athkar_elsabah_time_label.isHidden(), True)
DHUHR_DIR = gui.PRAYER_AUDIO_DIRS["dhuhr"]
os.makedirs(DHUHR_DIR, exist_ok=True)
timed(DHUHR_DIR, "zz-athan.mp3", 4 * 60)
tick(w.prayer_audio_lists["dhuhr"], {"zz-athan.mp3"})
dhuhr = w.get_today_prayer_times()["dhuhr"]
chk("an athan counts from its own time", end_text("dhuhr"),
    f"حتى {w.minutes_to_clock(dhuhr + 4)} · المدة 4 دقيقة".replace(gui.LTR_ISOLATE, "")
    .replace(gui.POP_ISOLATE, ""))
os.remove(os.path.join(DHUHR_DIR, "zz-athan.mp3"))
w.forget_deleted_audio("dhuhr", {"zz-athan.mp3"}, False)
w.cron_chk.setChecked(True)
w.cron_hour_spin.setValue(6); w.cron_min_spin.setValue(0)
tick(w.quran_audio_list, {"zz-long.mp3"})
w.warn_new_overlaps()
warned.clear()
chk("three hours of Quran from 6:00 ends at 9:00, clear of the Athkar", end_text("quran"),
    "حتى 9:00 AM · المدة 3:00 ساعة")
w.cron_hour_spin.setValue(7)
chk("a change waits for the finger to stop before warning", w.overlap_timer.isActive(), True)
w.overlap_timer.stop(); w.warn_new_overlaps()
chk("moved to 7:00 it runs into them, and says so", len(warned), 1)
chk("naming both, with when each plays",
    warned[-1].replace(gui.LTR_ISOLATE, "").replace(gui.POP_ISOLATE, "").splitlines()[1],
    "• «القرآن الكريم» (7:00 AM – 10:00 AM) مع «أذكار الصباح» (9:45 AM – 10:05 AM)")
chk("and that the form goes back", gui.OVERLAP_RESTORED_TEXT in warned[-1], True)
chk("closing it puts the Quran back at 6:00, the last time clear of them",
    (w.cron_hour_spin.value(), w.cron_min_spin.value(), end_text("quran")),
    (6, 0, "حتى 9:00 AM · المدة 3:00 ساعة"))
chk("with nothing left to check", w.overlap_timer.isActive(), False)
w.athkar_elsabah_hour_spin.setValue(8); w.athkar_elsabah_min_spin.setValue(15)
w.overlap_timer.stop(); w.warn_new_overlaps()
chk("Athkar Elsabah moved to 8:15, inside the Quran, is warned of and put back at 9:45",
    (len(warned), w.athkar_elsabah_hour_spin.value(), w.athkar_elsabah_min_spin.value()), (2, 9, 45))
w.athkar_elsabah_chk.setChecked(False); w.warn_new_overlaps()
w.cron_hour_spin.setValue(8); w.warn_new_overlaps()
chk("a change that meets nothing is kept, and becomes the one to go back to",
    (len(warned), w.cron_hour_spin.value()), (2, 8))
w.athkar_elsabah_chk.setChecked(True); w.warn_new_overlaps()
chk("switching an event on into an overlap is undone too",
    (len(warned), w.athkar_elsabah_chk.isChecked(), w.cron_hour_spin.value()), (3, False, 8))
w.cron_hour_spin.setValue(6); w.warn_new_overlaps()
w.athkar_elsabah_chk.setChecked(True); w.warn_new_overlaps()
chk("nothing is said when nothing meets", len(warned), 3)
saves = []
real_save = w.save_settings
w.save_settings = lambda *args, **kwargs: saves.append(1) or False
w.cron_hour_spin.setValue(7)
w.save_and_apply_settings()
chk("saving before the warning had its turn still warns, puts it back and saves nothing",
    (len(warned), w.cron_hour_spin.value(), saves, w.is_processing), (4, 6, [], False))
w.save_settings = real_save
from PyQt5.QtTest import QTest
hour_edit = w.cron_hour_spin.lineEdit()
QTest.mouseClick(hour_edit, Qt.LeftButton, pos=hour_edit.rect().center())
pad_key = lambda text: next(b for b in w.number_pad.findChildren(gui.QPushButton)
                            if b.text() == text).click()
pad_key("7"); pad_key("موافق")
chk("OK on the pad checks at once: the warning comes while the pad is still open",
    (len(warned), w.number_pad.isVisible()), (5, True))
chk("and the pad stays, showing the time put back, for another try",
    (w.cron_hour_spin.value(), w.number_pad.display.text()), (6, "6"))
pad_key("5"); pad_key("موافق")
chk("a time that meets nothing closes it", (len(warned), w.number_pad.isVisible(),
                                            w.cron_hour_spin.value()), (5, False, 5))
w.apply_config_to_ui()
chk("reloading the saved settings does not warn about them", (w.overlap_timer.isActive(),
                                                                len(warned)), (False, 5))
for directory, name in ((ATHKAR_DIR, "zz-athkar.mp3"), (QURAN_DIR, "zz-long.mp3")):
    os.remove(os.path.join(directory, name))
if made_athkar_dir:
    os.rmdir(ATHKAR_DIR)
if made_quran_dir:
    os.rmdir(QURAN_DIR)

print("10. a tap on a number field opens a pad to type it, inside the window")
from PyQt5.QtTest import QTest
from PyQt5.QtCore import QPoint
w.cron_chk.setChecked(True)
w.cron_hour_spin.setValue(7)
edit = w.cron_hour_spin.lineEdit()
QTest.mouseClick(edit, Qt.LeftButton, pos=edit.rect().center())
pad = w.number_pad
chk("it opens over the window, not as a window of its own",
    (pad.isVisible(), pad.parentWidget() is w, pad.isWindow()), (True, True, False))
chk("titled with the field's label", pad.title.text(), "الساعة")
ok_btn, cancel_btn = pad.ok_btn, pad.cancel_btn
digit = lambda t: next(b for b in pad.findChildren(gui.QPushButton) if b.text() == t)
chk("OK on the right as Arabic reads, the digits laid out as on a phone",
    (ok_btn.mapTo(pad, ok_btn.rect().center()).x() > cancel_btn.mapTo(pad, cancel_btn.rect().center()).x(),
     digit("1").mapTo(pad, QPoint(0, 0)).x() < digit("3").mapTo(pad, QPoint(0, 0)).x()), (True, True))
chk("showing the value it has", pad.display.text(), "7")
chk("and the range it takes", pad.hint.text().replace(gui.LTR_ISOLATE, "").replace(gui.POP_ISOLATE, ""),
    "من 0 إلى 23")
press = lambda text: next(b for b in pad.findChildren(gui.QPushButton) if b.text() == text).click()
press("1"); press("8")
chk("the first digit replaces it, the next add to it", pad.display.text(), "18")
press("5")
chk("no more digits than the largest value has", pad.display.text(), "18")
press("موافق")
chk("OK sets the field and closes", (w.cron_hour_spin.value(), pad.isVisible()), (18, False))
QTest.mouseClick(edit, Qt.LeftButton, pos=edit.rect().center())
press("⌫"); press("⌫"); press("9"); press("9")
press("موافق")
chk("a value out of range is not taken, and the range turns red",
    (w.cron_hour_spin.value(), pad.isVisible(), "#c62828" in pad.hint.styleSheet()), (18, True, True))
press("إلغاء")
chk("cancel leaves it as it was", (w.cron_hour_spin.value(), pad.isVisible()), (18, False))
QTest.mousePress(edit, Qt.LeftButton, pos=QPoint(2, 2))
QTest.mouseRelease(edit, Qt.LeftButton, pos=QPoint(2, 60))
chk("a swipe that starts on a field does not open it", pad.isVisible(), False)
w.cron_chk.setChecked(False)
QTest.mouseClick(edit, Qt.LeftButton, pos=edit.rect().center())
chk("nor does a tap on a field that is switched off", pad.isVisible(), False)
w.duha_chk.setChecked(True)
duha_edit = w.duha_spin.lineEdit()
QTest.mouseClick(duha_edit, Qt.LeftButton, pos=duha_edit.rect().center())
warned.clear()
press("5")
press("موافق")
chk("a typed value is checked like one stepped to: Duha 5 minutes before Dhuhr is refused",
    (len(warned), w.duha_spin.value() != 5), (1, True))
chk("and the pad stays open on the value kept",
    (pad.isVisible(), pad.display.text()), (True, str(w.duha_spin.value())))
press("إلغاء")

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
