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
# Releases only accumulate, and on a touchscreen a list taller than the panel puts the
# older versions out of reach. combobox-popup: 0 in the stylesheet is what makes the
# limit bind; without it the popup sizes itself to its contents and ignores it.
chk("five at a time, the rest a scroll away", w.update_version_combo.maxVisibleItems(), 5)
chk("and the popup is the kind that honours that",
    "combobox-popup: 0" in w.update_version_combo.styleSheet(), True)

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

print("4. a pin announces itself, and the button beside it is the way back")
# Test 2 left the device pinned, which is exactly the state a device being prepared for
# someone ends up in - and the state it must not ship in. A pin is otherwise invisible:
# the daily check quietly stops following the fleet, and there is no SSH into a device
# once it is in someone's home.
# isHidden() rather than isVisible(): the window is never shown in a headless run, so
# every child reports invisible regardless of what the code asked for.
w.refresh_update_status()
chk("a pinned device says so", w.update_pin_label.isHidden(), False)
chk("naming the version it is held on", chosen in w.update_pin_label.text(), True)
chk("and offers the way out", w.update_unpin_btn.isHidden(), False)
w.update_unpin_btn.click()
chk("which clears PIN", "PIN=\n" in open(CONF, encoding="utf-8").read(), True)
chk("and then there is nothing left to undo", w.update_pin_label.isHidden(), True)
chk("so the button goes too", w.update_unpin_btn.isHidden(), True)
# Turning the daily check off must not touch the pin - "not on a schedule" and "held on
# one version" are different questions, and التحديث إلى أحدث إصدار still works with it off.
w.update_auto_chk.setChecked(False)
chk("switching auto off leaves PIN alone",
    "PIN=\n" in open(CONF, encoding="utf-8").read(), True)
w.update_auto_chk.setChecked(True)

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

print("9. the rollback list offers the retained backup first, then older releases")
# Section 5 installed 1.1.0 over 1.0.0, so the device has a real backup of 1.0.0 on disk.
# Only one is ever kept - check_updates.sh clears the directory each time it takes a new
# one - so that entry is the only true restore in the list; everything under it has to be
# downloaded, which is why it appears only after the versions have been fetched.
w.refresh_update_status()
# Nothing is preselected: this button pins the device and moves it, so it takes a
# deliberate choice rather than a stray tap on an already-loaded version.
chk("nothing is chosen to begin with", w.update_rollback_combo.currentData(), "")
chk("and the button says so", w.update_rollback_btn.text(), "اختر إصدارًا للرجوع إليه")
chk("but the backup is the first real entry", w.update_rollback_combo.itemData(1), "1.0.0")
chk("marked as the local copy, in quotes",
    f'"{m.ROLLBACK_LOCAL_LABEL}"' in w.update_rollback_combo.itemText(1), True)
w.update_rollback_combo.setCurrentIndex(1)
chk("choosing it names it on the button", "1.0.0" in w.update_rollback_btn.text(), True)

# Nothing is offered that the device could not go back to: not the installed version, and
# not anything newer than it.
installed = w.read_update_status().get("installed", "")
w.update_published_versions = ["1.0.0", "1.0.5", "1.0.9", "1.0.10", installed, "9.9.9"]
w.populate_rollback_versions()
offered = [w.update_rollback_combo.itemData(i)
           for i in range(1, w.update_rollback_combo.count())]
chk("the placeholder still leads", w.update_rollback_combo.itemData(0), "")
chk("the installed version is not offered", installed in offered, False)
chk("nor anything newer", "9.9.9" in offered, False)
chk("the backup leads the real entries", offered[0], "1.0.0")
# Sorted by number, not by string - "1.0.10" is newer than "1.0.9" and sorts above it.
chk("older releases follow, newest first", offered[1:], ["1.0.10", "1.0.9", "1.0.5"])
chk("five at a time here too", w.update_rollback_combo.maxVisibleItems(), 5)

print("10. going back on purpose sticks")
# Without a pin the nightly check would put the device straight back on the version it was
# just taken off. The run itself is exercised by test_updater.sh; what matters here is
# which command the button chooses and what it writes first.
started = []
real_start = w.start_update
w.start_update = lambda args, text: started.append(args)

w.update_rollback_combo.setCurrentIndex(1)          # the retained backup
w.run_update_rollback()
chk("the local copy is restored, not downloaded", started[-1], ["--rollback"])
chk("and the device is pinned to it",
    "PIN=1.0.0" in open(CONF, encoding="utf-8").read(), True)

w.update_rollback_combo.setCurrentIndex(2)          # an older published release
chosen_old = w.update_rollback_combo.currentData()
w.run_update_rollback()
chk("anything else is fetched like any other version",
    started[-1], ["--target", chosen_old])
chk("and pinned just the same",
    f"PIN={chosen_old}" in open(CONF, encoding="utf-8").read(), True)

# Choosing nothing is refused rather than quietly doing the default thing.
seen.clear()
w.update_rollback_combo.setCurrentIndex(0)
w.run_update_rollback()
chk("the placeholder is refused", seen and seen[-1][0], "error")
chk("and no run was started", len(started), 2)

w.start_update = real_start
w.write_update_conf("PIN", "")   # leave the fixture following central again

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
