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

print("4. choosing nothing is refused, not silently ignored")
seen.clear()
w.update_version_combo.setCurrentIndex(0)
w.install_selected_version()
chk("an error was shown", seen and seen[-1][0], "error")

print("5. status text reflects the device after all of that")
w.refresh_update_status()
print("   ", w.update_status_label.text().replace("\n", " | "))
print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
