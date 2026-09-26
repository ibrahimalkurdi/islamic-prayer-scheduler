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
answer = [True]
def fake_confirm(parent, title, text):
    seen.append(("confirm", title, text))
    return answer[0]
m.arabic_confirm = fake_confirm
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

print("2. an older version asks first, and a yes turns the daily check off")
w.update_version_combo.setCurrentIndex(items.index("1.0.0"))
chosen = w.update_version_combo.currentData()
started = []
real_start = w.start_update
w.start_update = lambda args, text: started.append(args)
seen.clear(); answer[0] = False
w.install_selected_version()
chk("the user is asked", seen and seen[-1][0], "confirm")
chk("naming the version", chosen in seen[-1][2], True)
chk("a no installs nothing", started, [])
chk("and leaves the daily check on", w.update_auto_chk.isChecked(), True)
w.update_version_combo.setCurrentIndex(items.index("1.1.0"))
seen.clear()
w.install_selected_version()
chk("the latest version is not questioned", [k for k, *_ in seen], [])
chk("and installs", started, [["--target", "1.1.0"]])
started.clear()
w.update_version_combo.setCurrentIndex(items.index("1.0.0"))
w.start_update = real_start
answer[0] = True
w.install_selected_version()
w.update_worker.wait(120000); app.processEvents()
conf = open(CONF, encoding="utf-8").read()
chk("a yes unticks the daily check", w.update_auto_chk.isChecked(), False)
chk("ENABLED=false written", "ENABLED=false" in conf, True)
chk("no PIN written", f"PIN={chosen}" in conf, False)
status = json.loads(subprocess.run(["/bin/bash", os.path.join(os.environ["HOME"],
    "Desktop/scheduler/config/scripts/check_updates.sh"), "--status"],
    capture_output=True, text=True).stdout)
chk("device moved to the chosen version", status["installed"], chosen)
chk("status shows no pin", status["pinned"], "")

print("3. ticking the box on an older version asks before moving the device")
# The device is on 1.0.0 and the pointer names 1.1.0. Moves are recorded, not run, until
# section 5 - which needs the device still behind the pointer.
chk("--latest names the pointer's version", w.read_latest_version(), "1.1.0")
started = []
w.start_update = lambda args, text: started.append(args)
w.refresh_update_status()
seen.clear(); answer[0] = False
w.update_auto_chk.setChecked(True)
chk("the user is asked", seen and seen[-1][0], "confirm")
chk("naming both versions", chosen in seen[-1][2] and "1.1.0" in seen[-1][2], True)
chk("a no leaves the box unticked", w.update_auto_chk.isChecked(), False)
chk("and ENABLED false", "ENABLED=false" in open(CONF, encoding="utf-8").read(), True)
chk("and moves nothing", started, [])
answer[0] = True
w.update_auto_chk.setChecked(True)
chk("a yes ticks it", w.update_auto_chk.isChecked(), True)
chk("writes ENABLED=true", "ENABLED=true" in open(CONF, encoding="utf-8").read(), True)
chk("and moves the device to the latest now", started, [["--now"]])
w.update_auto_chk.setChecked(False)
chk("unticking writes ENABLED=false", "ENABLED=false" in open(CONF, encoding="utf-8").read(), True)
real_latest = w.read_latest_version
w.read_latest_version = lambda: chosen
seen.clear(); started.clear()
w.update_auto_chk.setChecked(True)
chk("already on the latest: no question", [k for k, *_ in seen], [])
chk("and nothing to move", started, [])
w.read_latest_version = lambda: ""
w.update_auto_chk.setChecked(False)
w.update_auto_chk.setChecked(True)
chk("pointer unreachable: enabled without asking", [k for k, *_ in seen], [])
w.read_latest_version = real_latest

print("4. only the checkbox holds the device, and it says so in red")
# isHidden() rather than isVisible(): the window is never shown in a headless run, so
# every child reports invisible regardless of what the code asked for.
w.update_auto_chk.setChecked(True)
w.refresh_update_status()
chk("auto on: no hold notice", w.update_pin_label.isHidden(), True)
chk("the old way-out button is gone", hasattr(w, "update_unpin_btn"), False)
w.update_auto_chk.setChecked(False)
chk("auto off: the hold notice shows", w.update_pin_label.isHidden(), False)
chk("naming the installed version", chosen in w.update_pin_label.text(), True)
chk("in red", "#dc3545" in w.update_pin_label.styleSheet(), True)
chk("switching auto off writes no PIN",
    "PIN=\n" in open(CONF, encoding="utf-8").read(), True)
w.update_auto_chk.setChecked(True)
chk("auto on again: the notice goes", w.update_pin_label.isHidden(), True)

# A PIN left by an older release holds the device too, so it must not hide behind a
# ticked box - it shows as off, and ticking the box is what clears it.
w.write_update_conf("PIN", chosen)
w.refresh_update_status()
chk("a leftover PIN shows as auto off", w.update_auto_chk.isChecked(), False)
chk("with the hold notice", w.update_pin_label.isHidden(), False)
w.update_auto_chk.setChecked(True)
conf = open(CONF, encoding="utf-8").read()
chk("ticking clears the PIN", "PIN=\n" in conf, True)
chk("and enables updates", "ENABLED=true" in conf, True)
chk("and the notice goes", w.update_pin_label.isHidden(), True)
w.start_update = real_start

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

print("10. going back picks the right command and pins nothing")
# The run itself is exercised by test_updater.sh; what matters here is which command the
# button chooses, and that holding the device stays the checkbox's job alone.
started = []
real_start = w.start_update
w.start_update = lambda args, text: started.append(args)

w.update_auto_chk.setChecked(True)
seen.clear()
w.update_rollback_combo.setCurrentIndex(1)          # the retained backup
w.run_update_rollback()
chk("going back asks first", seen and seen[-1][0], "confirm")
chk("and a yes unticks the daily check", w.update_auto_chk.isChecked(), False)
chk("the local copy is restored, not downloaded", started[-1], ["--rollback"])
chk("and the device is not pinned to it",
    "PIN=1.0.0" in open(CONF, encoding="utf-8").read(), False)

w.update_rollback_combo.setCurrentIndex(2)          # an older published release
chosen_old = w.update_rollback_combo.currentData()
w.run_update_rollback()
chk("anything else is fetched like any other version",
    started[-1], ["--target", chosen_old])
chk("and not pinned either",
    f"PIN={chosen_old}" in open(CONF, encoding="utf-8").read(), False)

# Choosing nothing is refused rather than quietly doing the default thing.
seen.clear()
w.update_rollback_combo.setCurrentIndex(0)
w.run_update_rollback()
chk("the placeholder is refused", seen and seen[-1][0], "error")
chk("and no run was started", len(started), 2)

w.start_update = real_start

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
