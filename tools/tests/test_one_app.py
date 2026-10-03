"""«السكينة» as one app: the time screen's ⚙ opens Settings, closing Settings comes back to
the time screen, and the desktop entries carry the new names.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_one_app.py
"""
import os, sys, importlib.util

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
TIME_APP = os.path.join(SCHEDULER, "applications/desktop/prayer_times_gui/main.py")
SETTINGS_APP = os.path.join(SCHEDULER, "applications/desktop/scheduler_settings_gui/main.py")

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


def load(path, name):
    sys.path.insert(0, os.path.dirname(path))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry_name(file_name):
    with open(os.path.join(SCHEDULER, "config", file_name), encoding="utf-8") as f:
        return next(line[5:].strip() for line in f if line.startswith("Name="))


print("1. the desktop entries")
chk("the app is «السكينة»", entry_name("prayer_times_gui.desktop"), "السكينة")
chk("Settings, on the desktop too, is «إعدادات السكينة»",
    entry_name("scheduler_settings_gui.desktop"), "إعدادات السكينة")
with open(os.path.join(SCHEDULER, "config/scheduler_settings_gui.desktop"), encoding="utf-8") as f:
    settings_exec = next(line.strip() for line in f if line.startswith("Exec="))
chk("its icon asks for the copy ⚙ keeps ready, on X as ⚙ starts it",
    (settings_exec.endswith("main.py --open"), "QT_QPA_PLATFORM=xcb" in settings_exec), (True, True))
needs = [l.strip() for l in open(os.path.join(SCHEDULER, "config/needs_init"), encoding="utf-8")
         if l.strip() and not l.lstrip().startswith("#")]
import re
chk("the release asks for setup, so the desktop changes on update",
    bool(needs and re.fullmatch(r"\d+\.\d+\.\d+", needs[0])), True)

from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)

print("2. the time screen's ⚙")
page = load(TIME_APP, "time_app")
counter = page.AdhanCounter()
counter.showNormal(); counter.setFixedSize(800, 480); app.processEvents()
button = counter.settings_btn
chk("a fifth window button", button.geometry().left(),
    page.WINDOW_BUTTON_LEFT + 4 * page.WINDOW_BUTTON_PITCH)
chk("the notice and the banner stay clear of it",
    button.geometry().right() < page.WINDOW_BUTTONS_RIGHT_EDGE, True)
chk("the Settings it opens is there", os.path.isfile(page.SETTINGS_APP), True)

started_settings = []
page.start_settings = lambda *flags: started_settings.append(flags)
counter.prewarm_settings()
chk("no Settings is kept ready off screen - the update's check runs this app there",
    started_settings, [])
page.settings_app_pids = lambda: []
button.click()
chk("with none running, ⚙ starts Settings to show at once", started_settings, [("--present",)])
signalled = []
real_kill = page.os.kill
page.os.kill = lambda pid, sig: signalled.append((pid, sig))
page.settings_app_pids = lambda: [4242]
button.click()
page.os.kill = real_kill
chk("with one running, ⚙ asks it to show itself - no second copy",
    (signalled, len(started_settings)), ([(4242, page.signal.SIGUSR1)], 1))

print("3. closing Settings comes back to the time screen")
gui = load(SETTINGS_APP, "settings_app")
gui.arabic_info = lambda parent, title, text: None
gui.arabic_error = lambda parent, title, text: None
started = []
gui.launch_countdown = lambda: started.append(1)
settings = gui.ControlApp()
settings.show()

gui.countdown_running = lambda: False
settings.close()
chk("the time screen is started when it is not running", started, [1])

settings.show(); started.clear()
gui.countdown_running = lambda: True
settings.close()
chk("and left alone when it is", started, [])

class Installing:
    def isRunning(self):
        return True

settings.show(); started.clear()
gui.countdown_running = lambda: False
settings.update_worker = Installing()
settings.close()
chk("not while an update is installing - the updater restarts it", started, [])
chk("the time app it starts is there", os.path.isfile(gui.COUNTDOWN_APP), True)

settings.update_worker = None
settings.set_opened_from_desktop(True)
settings.show(); started.clear()
settings.close()
chk("opened from the desktop it is closed with «إغلاق», back to the desktop",
    (settings.back_btn.text(), started), ("✖ إغلاق", []))
settings.set_opened_from_desktop(False)
chk("opened from ⚙ it is «رجوع»", settings.back_btn.text(), "→ رجوع")

print("4. Settings kept ready: shown at once, hidden on close, never stale")
import time
def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents(); time.sleep(0.02)

class FakeApp:
    quit_called = False
    def quit(self):
        FakeApp.quit_called = True

gui.countdown_running = lambda: True
kept = gui.BackgroundSettings(FakeApp(), present_now=False)
first = kept.window
chk("built ahead, hidden", (first is not None, first.isVisible()), (True, False))
chk("its network check waits until it is shown", first.internet_timer.isActive(), False)
kept.present(); pump(0.2)
chk("shown on request, full screen", (first.isVisible(), first.isFullScreen()), (True, True))
first.close(); pump(0.2)
chk("closing hides it rather than ending it", (first.isVisible(), kept.window is first), (False, True))
pump(2.0)
chk("and a fresh copy is built for next time", kept.window is not first, True)
second = kept.window
kept.present(); pump(0.2)
chk("which is the one shown next, with nothing changed", kept.window is second, True)
chk("from ⚙, its way out is «رجوع»", second.back_btn.text(), "→ رجوع")
second.close(); pump(0.2)
kept.present(from_desktop=True); pump(0.2)
chk("from the desktop icon, the same copy shows «إغلاق»",
    (kept.window is second, second.back_btn.text()), (True, "✖ إغلاق"))
second.close(); pump(2.0)
third = kept.window
os.utime(gui.SETTINGS_INI_FILE)
kept.data = (None,)
kept.present(); pump(0.2)
chk("rebuilt before showing when what it reads has changed", kept.window is not third, True)
kept.window.close(); pump(0.3)
spawned = []
real_popen = gui.subprocess.Popen
gui.subprocess.Popen = lambda args, **kw: spawned.append(args)
kept.code = ("old",)
kept.present()
gui.subprocess.Popen = real_popen
chk("restarted when an update replaced its code", (spawned[0][-2:], FakeApp.quit_called),
    (["--background", "--present"], True))
gui.subprocess.Popen = lambda args, **kw: spawned.append(args)
kept.present(from_desktop=True)
gui.subprocess.Popen = real_popen
chk("and still opened as from the desktop when that is where it was asked from",
    spawned[1][-3:], ["--background", "--present", "--desktop"])

shown = []
timer = gui.on_show_request(shown.append)
os.kill(os.getpid(), gui.signal.SIGUSR1); pump(0.5)
chk("the signal from ⚙ shows it as the time app's page", shown, [False])
os.kill(os.getpid(), gui.signal.SIGUSR2); pump(0.5)
chk("the one from the desktop icon shows it as an app of its own", shown, [False, True])

print("5. the desktop's Settings icon")
import subprocess
handles = subprocess.Popen([sys.executable, "-c",
    "import signal, time; signal.signal(signal.SIGUSR2, lambda *a: None); time.sleep(30)"])
old_copy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
time.sleep(0.5)
gui.other_settings_pids = lambda: [handles.pid]
chk("with Settings kept ready, the icon shows it - no second copy", gui.show_running_copy(), True)
chk("asking with the desktop's signal, which leaves it running", handles.poll(), None)
gui.other_settings_pids = lambda: [old_copy.pid]
chk("a copy from before 1.5.1 is ended by that signal, so the icon starts a new one",
    gui.show_running_copy(), False)
handles.kill(); handles.wait(); old_copy.wait()
gui.other_settings_pids = lambda: []
chk("with none, the icon starts the copy that is kept from then on", gui.show_running_copy(), False)

print("6. muted, the time app says when the sound comes back, on both pages")
from datetime import datetime as _datetime
expiry = int(_datetime.now().timestamp()) + 3600
page.mute_expiry = lambda: expiry
page.is_muted = lambda: True
page.audio_is_muted = lambda: True
page.audio_set_mute = lambda muted: True
counter.audio_poll_due = 0
counter.sync_mute_state()
line = counter.mute_until.text()
chk("a muted device shows the line, naming the time it lapses",
    (counter.mute_until.isHidden(), line.startswith("الصوت مكتوم حتى"),
     page.clock_12h(_datetime.fromtimestamp(expiry)).strip() in line), (False, True, True))
if counter.stack.currentWidget() is counter.counter_page:
    counter.toggle_view()
chk("the daily list shows it too", counter.mute_until.isHidden(), False)
chk("in the buttons' colour, not the muted red",
    counter.page_button_color in counter.mute_until.styleSheet(), True)
page.mute_expiry = lambda: None
counter.audio_poll_due = 0
counter.sync_mute_state()
chk("silenced with no deadline, it says only that", counter.mute_until.text(), "الصوت مكتوم")
page.is_muted = lambda: False
page.audio_is_muted = lambda: False
counter.audio_poll_due = 0
counter.sync_mute_state()
chk("and it goes when the sound is back", counter.mute_until.isHidden(), True)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
