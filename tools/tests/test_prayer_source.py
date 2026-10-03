"""The prayer-times picker: it offers the cities and Al Awail exports, opens on the one in
use, says that the choice is copied into the Desktop reference file, and can copy the
current source in again over hand edits.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_prayer_source.py
"""
import os, sys, shutil, importlib.util

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
SETTINGS_APP = os.path.join(SCHEDULER, "applications/desktop/scheduler_settings_gui/main.py")

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


sys.path.insert(0, os.path.dirname(SETTINGS_APP))
spec = importlib.util.spec_from_file_location("settings_app", SETTINGS_APP)
gui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gui)
from PyQt5.QtWidgets import QApplication, QDialog
app = QApplication(sys.argv)

BERLIN = os.path.join(gui.PRAYERS_CONFIG_DIR, "برلين.csv")
AACHEN = os.path.join(gui.PRAYERS_CONFIG_DIR, "آخن.csv")
REFERENCE = gui.PRAYER_CSV_FILE
AWAIL = os.path.join(gui.DESKTOP_DIR, "دمشق-2026.csv")

print("1. what is offered")
open(AWAIL, "w").close()
sources = gui.scan_prayer_sources()
chk("the cities first", [os.path.basename(p) for p in sources[:3]], ["آخن.csv", "برلين.csv", "دمشق.csv"])
chk("then an Al Awail export from the Desktop", AWAIL in sources, True)
chk("never the reference file itself - picking it changes nothing", REFERENCE in sources, False)
os.remove(AWAIL)

print("2. the source in use")
chk("found where it was recorded", gui.current_prayer_source(BERLIN), BERLIN)
chk("a preset recorded under another device's home is this device's preset",
    gui.current_prayer_source("/home/louay/Desktop/scheduler/config/prayers-config/برلين.csv"), BERLIN)
chk("an export no longer on the Desktop cannot be restored from",
    gui.current_prayer_source(os.path.join(gui.DESKTOP_DIR, "حلب-2025.csv")), None)
chk("nor can nothing", gui.current_prayer_source(""), None)

print("3. the window")
dialog = gui.PrayerSourceDialog(None, current_source=BERLIN)
chk("opens on the city in use", dialog.combo.currentData(), BERLIN)
chk("the yellow note names the file the choice is copied into",
    "إدخال-مواقيت-الصلاة-للمستخدم.csv" in dialog.note.text(), True)
chk("and says to save", "حفظ وتفعيل الإعدادات" in dialog.note.text(), True)
chk("beside «استعادة مواقيت المدينة», what it copies where",
    ("برلين.csv" in dialog.restore_note.text(), dialog.restore_btn.isEnabled()), (True, True))
chk("file names are kept whole inside the Arabic", "⁨برلين.csv⁩" in dialog.restore_note.text(), True)
unknown = gui.PrayerSourceDialog(None, current_source=None)
chk("with no known source there is nothing to restore", unknown.restore_btn.isEnabled(), False)

print("4. restoring")
gui.arabic_confirm = lambda parent, title, text: False
dialog = gui.PrayerSourceDialog(None, current_source=BERLIN)
dialog.restore_btn.click()
chk("declined, nothing happens", (dialog.result(), dialog.restore), (0, False))
gui.arabic_confirm = lambda parent, title, text: True
dialog.restore_btn.click()
chk("confirmed, it returns the source in use as a restore",
    (dialog.result(), dialog.selected_path, dialog.restore), (QDialog.Accepted, BERLIN, True))

asked = []
gui.arabic_confirm = lambda parent, title, text: asked.append(title) or True
gui.arabic_info = lambda parent, title, text: None
gui.arabic_error = lambda parent, title, text: None
window = gui.ControlApp()
shutil.copyfile(BERLIN, REFERENCE)
with open(REFERENCE, "a", encoding="utf-8") as f:
    f.write("\n")
asked.clear()
chk("a restore overwrites hand edits", window.resolve_and_apply_prayer_source(BERLIN, confirmed=True), True)
chk("without asking a second time - the button already asked", asked, [])
chk("and the reference file is the city again",
    open(REFERENCE, "rb").read() == open(BERLIN, "rb").read(), True)

with open(REFERENCE, "a", encoding="utf-8") as f:
    f.write("\n")
asked.clear()
window.resolve_and_apply_prayer_source(AACHEN)
chk("picking another city over hand edits still warns", asked, ["تنبيه"])
chk("the city picked is recorded", window.config["Settings"][gui.PRAYER_SOURCE_LABEL_KEY], AACHEN)
window.resolve_and_apply_prayer_source(BERLIN, confirmed=True)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
