import os, sys, importlib.util, json, subprocess
os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")
os.environ["HEALTH_SETTLE_SECONDS"] = "1"
APP = os.path.join(os.environ["HOME"], "Desktop/scheduler/applications/desktop/scheduler_settings_gui/main.py")
CONF = os.path.join(os.environ["HOME"], "Desktop/scheduler/config/update.conf")
sys.path.insert(0, os.path.dirname(APP))
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
spec = importlib.util.spec_from_file_location("settings_app", APP)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# popups would block a headless run; record them instead
seen = []
m.arabic_info  = lambda parent, title, text: seen.append(("info", title, text))
m.arabic_error = lambda parent, title, text: seen.append(("error", title, text))
w = m.ControlApp()
fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)

print("1. version list is fetched and offered newest-first")
w.load_available_versions()
items = [w.update_version_combo.itemData(i) for i in range(w.update_version_combo.count())]
chk("placeholder then versions", items[0], "")
chk("newest first", items[1], "1.1.0")

print("2. installing a chosen version pins the device to it")
w.update_version_combo.setCurrentIndex(items.index("1.0.0") if "1.0.0" in items else 1)
chosen = w.update_version_combo.currentData()
w.install_selected_version()
w.update_worker.wait(120000); app.processEvents()
conf = open(CONF, encoding="utf-8").read()
chk("PIN written", f"PIN={chosen}" in conf, True)
status = json.loads(subprocess.run(["/bin/bash", os.path.join(os.environ["HOME"],
    "Desktop/scheduler/config/scripts/check_updates.sh"), "--status"],
    capture_output=True, text=True).stdout)
chk("device moved to the chosen version", status["installed"], chosen)
chk("status shows the pin", status["pinned"], chosen)

print("3. the auto-update checkbox writes ENABLED")
w.update_auto_chk.setChecked(False)
chk("ENABLED=false written", "ENABLED=false" in open(CONF, encoding="utf-8").read(), True)
w.update_auto_chk.setChecked(True)
chk("ENABLED=true written", "ENABLED=true" in open(CONF, encoding="utf-8").read(), True)

print("4. the follow-central checkbox is the only way back from a pin")
# Test 2 left the device pinned, which is exactly the state a device being prepared for
# someone ends up in - and the state it must not ship in.
w.refresh_update_status()
chk("a pinned device shows unticked", w.update_follow_chk.isChecked(), False)
w.update_follow_chk.setChecked(True)
chk("ticking clears PIN", "PIN=\n" in open(CONF, encoding="utf-8").read(), True)
chk("and it stays ticked after a refresh", w.update_follow_chk.isChecked(), True)
# Unticking has to pin to something; the installed version is the only safe choice.
installed = w.read_update_status().get("installed", "")
w.update_follow_chk.setChecked(False)
chk("unticking pins to the installed version",
    f"PIN={installed}" in open(CONF, encoding="utf-8").read(), True)
w.update_follow_chk.setChecked(True)

print("5. the result dialog says what actually happened")
# check_updates.sh exits 0 for several outcomes that are not an install, and the app used
# to report every one of them as "تم التحديث بنجاح" - including the case where the device
# never reached GitHub at all.
def run_update(args):
    seen.clear()
    w.start_update(args, "…")
    w.update_worker.wait(120000); app.processEvents()
    return seen[-1] if seen else (None, None, None)

# The device is unpinned and behind the pointer here, so this one really does install -
# which is what makes the second run below a genuine no-op rather than a rigged one.
kind, title, text = run_update(["--now"])
chk("a real update is reported as one", "تم التحديث بنجاح" in text, True)
chk("and asks the user to relaunch the countdown",
    "شغّل تطبيق مواقيت الصلاة" in text, True)

# Second run, nothing left to do: nothing was installed and nothing was stopped.
kind, title, text = run_update(["--now"])
chk("already current is not reported as an update", "تم التحديث بنجاح" in text, False)
chk("it says the device is current", "أنت تستخدم أحدث إصدار" in text, True)
chk("and does not ask the user to relaunch anything",
    "شغّل تطبيق مواقيت الصلاة" in text, False)

# An unreachable pointer is a failure to check, not a successful update.
import shutil
POINTER = os.path.join(HERE, "releases", "VERSIONS.json")
shutil.move(POINTER, POINTER + ".away")
kind, title, text = run_update(["--now"])
chk("an unreachable pointer is an error, not a success", kind, "error")
chk("and says nothing changed", "لم يتغيّر شيء على الجهاز" in text, True)
shutil.move(POINTER + ".away", POINTER)

print("6. choosing nothing is refused, not silently ignored")
seen.clear()
w.update_version_combo.setCurrentIndex(0)
w.install_selected_version()
chk("an error was shown", seen and seen[-1][0], "error")

print("7. status text reflects the device after all of that")
w.refresh_update_status()
print("   ", w.update_status_label.text().replace("\n", " | "))
print("8. the window carries an icon of its own")
# A QIcon over a missing file is null and says nothing about it, which is how the app
# spent its whole life pointing at an icon.ico that has never existed in this repo.
chk("window icon loaded", not w.windowIcon().isNull(), True)
chk("and it has real pixmaps in it", bool(w.windowIcon().availableSizes()), True)

# The countdown app carries the other half of the same bug: it never set an icon at all.
# It is checked here rather than in a suite of its own because there is nothing else
# about it that runs off-device - it wants a screen and today's prayer map.
COUNTDOWN = os.path.join(os.environ["HOME"],
    "Desktop/scheduler/applications/desktop/prayer_times_gui/main.py")
cspec = importlib.util.spec_from_file_location("countdown_app", COUNTDOWN)
c = importlib.util.module_from_spec(cspec); cspec.loader.exec_module(c)
chk("countdown icon loaded", not c.app_icon().isNull(), True)
chk("and it has real pixmaps in it too", bool(c.app_icon().availableSizes()), True)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
