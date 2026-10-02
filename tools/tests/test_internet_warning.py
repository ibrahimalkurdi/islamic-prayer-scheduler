"""The no-internet warning: when it shows, when it says the internet is back, and where it
sits on the time app and the Settings app. And the wifi picker the time app opens when
there is no network at all.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_internet_warning.py
"""
import os, sys, socket, importlib.util, configparser, time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
APPLICATIONS = os.path.join(SCHEDULER, "applications")
TIME_APP = os.path.join(APPLICATIONS, "desktop/prayer_times_gui/main.py")
sys.path.insert(0, os.path.dirname(TIME_APP))
SETTINGS_APP = os.path.join(APPLICATIONS, "desktop/scheduler_settings_gui/main.py")
SETTINGS_INI_FILE = os.path.join(SCHEDULER, "config/config.ini")

sys.path.insert(0, APPLICATIONS)
from shared import internet_status as net

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


print("0. an app that starts offline warns at once")
w = net.InternetWatch()
w.record(False, 0)
chk("no five-minute wait at launch", w.state(0), "offline")
w.dismiss()
chk("closing it hides it", w.state(1), "ok")
w = net.InternetWatch()
w.record(False, 2)
chk("and the next launch, still offline, warns again", w.state(2), "offline")
w = net.InternetWatch()
w.record(True, 0)
chk("an app that starts online is quiet", w.state(0), "ok")

print("1. a short drop says nothing")
w = net.InternetWatch()
w.record(True, 0)
w.record(False, 10)
w.record(False, 10 + net.WARN_AFTER_SECONDS - 1)
chk("still quiet a second short of five minutes", w.state(10 + net.WARN_AFTER_SECONDS - 1), "ok")
w.record(True, 400)
chk("and coming back from it is not announced", w.state(401), "ok")

print("2. five minutes down warns, and the warning stays")
w = net.InternetWatch()
w.record(False, 0)
w.record(False, net.WARN_AFTER_SECONDS)
chk("warns at five minutes", w.state(net.WARN_AFTER_SECONDS), "offline")
chk("with the inaccuracy in the words", "غير دقيقة" in w.message(net.WARN_AFTER_SECONDS)[0], True)
w.record(False, 3600)
chk("still warning an hour later", w.state(3600), "offline")

print("3. back online is said for ten seconds, then nothing")
w.record(True, 4000)
chk("back", w.state(4000), "back")
chk("in green", w.message(4000)[1], net.BACK_BG)
chk("still back at 9 seconds", w.state(4000 + net.BACK_SHOWN_SECONDS - 1), "back")
chk("gone at 10", w.state(4000 + net.BACK_SHOWN_SECONDS), "ok")

print("3b. the warning can be closed for the rest of the outage")
w = net.InternetWatch()
w.dismiss()
chk("closing before there is a warning does nothing", w.dismissed, False)
w.record(False, 0); w.record(False, net.WARN_AFTER_SECONDS)
w.dismiss()
chk("closed", w.state(net.WARN_AFTER_SECONDS + 1), "ok")
w.record(False, 3600)
chk("and stays closed while the outage lasts", w.state(3600), "ok")
w.record(True, 4000)
chk("the internet coming back is still said", w.state(4000), "back")
w.record(False, 5000); w.record(False, 5000 + net.WARN_AFTER_SECONDS)
chk("the next outage warns again", w.state(5000 + net.WARN_AFTER_SECONDS), "offline")

print("4. dropping again during the back message starts the count again")
w = net.InternetWatch()
w.record(False, 0); w.record(False, 300); w.record(True, 310)
w.record(False, 312)
chk("not back any more, and not warning yet either", w.state(313), "ok")
w.record(False, 312 + net.WARN_AFTER_SECONDS)
chk("warns again after its own five minutes", w.state(312 + net.WARN_AFTER_SECONDS), "offline")

print("5. reachable() asks the network and gives up on a dead end")
listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(1)
open_port = listener.getsockname()[1]
closed = socket.socket(); closed.bind(("127.0.0.1", 0)); closed_port = closed.getsockname()[1]
closed.close()
chk("a port that answers", net.reachable((("127.0.0.1", open_port),), timeout=1), True)
chk("a port that does not", net.reachable((("127.0.0.1", closed_port),), timeout=1), False)
chk("any one answering is enough",
    net.reachable((("127.0.0.1", closed_port), ("127.0.0.1", open_port)), timeout=1), True)
listener.close()


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


def settle(monitor):
    """Let the background check started by the last poll() finish."""
    for _ in range(100):
        if not monitor._running:
            return
        time.sleep(0.01)


def write_ini(enabled):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(SETTINGS_INI_FILE, encoding="utf-8")
    parser["Settings"][net.ENABLE_KEY] = str(enabled)
    with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
        parser.write(f)
    # The monitor rereads only on a new modification time; make sure there is one.
    stamp = time.time() + (1 if enabled else 2)
    os.utime(SETTINGS_INI_FILE, (stamp, stamp))


saved_ini = open(SETTINGS_INI_FILE, encoding="utf-8").read()
MAP_FILE = os.path.join(os.path.dirname(TIME_APP), "prayer_times_map.py")
saved_map = open(MAP_FILE, encoding="utf-8").read()
try:
    print("6. the monitor checks in the background, every 30 seconds")
    online = [False]
    calls = []
    def probe():
        calls.append(1)
        return online[0]
    clock = Clock()
    write_ini(True)
    m = net.InternetMonitor(SETTINGS_INI_FILE, probe=probe, clock=clock)
    chk("nothing to say at first", m.poll(), None)
    settle(m)
    clock.now += 1; m.poll(); settle(m)
    chk("one check, not one a second", len(calls), 1)
    for _ in range(net.WARN_AFTER_SECONDS // net.CHECK_EVERY_SECONDS + 1):
        clock.now += net.CHECK_EVERY_SECONDS
        m.poll(); settle(m)
    clock.now += 1
    chk("warning after five minutes of failed checks", m.poll()[0], net.OFFLINE_MESSAGE)

    print("7. the owner can switch it off, and on again")
    write_ini(False)
    clock.now += 1
    chk("off: nothing shown", m.poll(), None)
    write_ini(True)
    clock.now += 1
    chk("on again: the warning is back straight away", m.poll()[0], net.OFFLINE_MESSAGE)
    settle(m)

    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)

    print("8. the time app: top strip on the countdown, the corner by the date on the list")
    # Real times for every day, so the daily list is as full as it gets - with the
    # time-remaining badge up, its cards reach the bottom of the screen. The fixture's own
    # map has one day, and a list with no times is shorter than any device's.
    with open(os.path.join(SCHEDULER, "config/prayers-config/برلين.csv"), encoding="utf-8") as f:
        days = list(__import__("csv").DictReader(f))
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        f.write("prayerTimes = [\n" + ",\n".join(
            '{"Month":"%s","Day":"%s","Fajr":"%s","Sunrise":"%s","Dhuhr":"%s","Asr":"%s",'
            '"Maghrib":"%s","Isha":"%s"}' % (d["Month"], d["Day"], d["Fajr"], d["Sunrise"],
                                             d["Dhuhr"], d["Asr"], d["Maghrib"], d["Isha"])
            for d in days) + "\n]\n")
    page = load(TIME_APP, "time_app")
    counter = page.AdhanCounter()
    counter.showNormal(); counter.setFixedSize(800, 480); app.processEvents()
    counter.internet.poll = lambda: None
    counter.tick(); app.processEvents()
    chk("no banner while online", counter.internet_banner.isVisible(), False)
    offline = (net.OFFLINE_MESSAGE, net.OFFLINE_BG)
    counter.title.setVisible(False)
    counter.show_internet_banner(offline); app.processEvents()
    box = counter.internet_banner.geometry()
    chk("shown on the countdown", counter.internet_banner.isVisible(), True)
    chk("clear of the window buttons", box.left() > page.WINDOW_BUTTONS_RIGHT_EDGE, True)
    chk("above the prayer name's ink",
        box.bottom() < page.COUNTDOWN_NAME_INK_TOP_RATIO * 480, True)
    chk("orange on the ordinary background",
        net.OFFLINE_BG.lower() in counter.internet_banner.styleSheet().lower(), True)
    for warm in (page.COUNTDOWN_BG_RED, page.COUNTDOWN_BG_MAKROOH):
        counter.paint_counter_page(warm)
        counter.show_internet_banner(offline)
        chk(f"dark blue on {warm}, where orange would be lost",
            page.INTERNET_BANNER_ON_WARM_BG.lower() in counter.internet_banner.styleSheet().lower(),
            True)
    counter.paint_counter_page(page.COUNTDOWN_BG_DEFAULT)
    counter.title.setText(page.MAKROOH_NAFL_NOTICE); counter.title.setVisible(True)
    counter.show_internet_banner(offline)
    chk("it gives way to the makrooh notice", counter.internet_banner.isVisible(), False)
    counter.title.setVisible(False)
    counter.toggle_view(); app.processEvents()
    counter.show_internet_banner(offline); app.processEvents()
    box = counter.internet_banner.geometry()
    chk("shown on the daily list", counter.internet_banner.isVisible(), True)
    chk("in its shorter words", counter.internet_banner.text(), net.SHORT_OFFLINE_MESSAGE)
    from PyQt5.QtCore import QRect
    def on_screen(widget):
        return QRect(widget.mapTo(counter, widget.rect().topLeft()), widget.size())
    covered = [w for w in counter.daily_page.findChildren(page.QWidget)
               if w.isVisible() and isinstance(w, (page.QPushButton, page.QLabel, page.PrayerCard))
               and on_screen(w).intersects(box)]
    chk("covering nothing on the list - not the date, a card or the badge", covered, [])
    chk("inside the screen", box.right() < 800 and box.bottom() < 480, True)
    chk("with a close button on it", (counter.internet_close.isVisible(),
        box.contains(counter.internet_close.geometry())), (True, True))
    closed = []
    counter.internet.dismiss = lambda: closed.append(1)
    counter.internet_close.click()
    chk("tapping it closes the warning, for the outage",
        (counter.internet_banner.isVisible(), counter.internet_close.isVisible(), closed),
        (False, False, [1]))
    counter.show_internet_banner((net.BACK_MESSAGE, net.BACK_BG))
    chk("the green message has no close button", counter.internet_close.isVisible(), False)
    counter.show_internet_banner(None)
    chk("and gone when there is nothing to say", counter.internet_banner.isVisible(), False)

    print("9. the Settings app: a checkbox, on by default, and the banner over the page")
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(saved_ini)
    parser.remove_option("Settings", net.ENABLE_KEY)
    with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
        parser.write(f)
    gui = load(SETTINGS_APP, "settings_app")
    gui.arabic_info = lambda parent, title, text: None
    gui.arabic_error = lambda parent, title, text: None
    settings = gui.ControlApp(); settings.show(); app.processEvents()
    chk("on for a device that never chose", settings.internet_warning_chk.isChecked(), True)
    settings.internet.poll = lambda: offline
    settings.refresh_internet_banner(); app.processEvents()
    chk("the banner shows, with its close button", (settings.internet_bar.isVisible(),
        settings.internet_close.isVisible()), (True, True))
    chk("above the scrolling page, so always in view",
        settings.internet_bar.parentWidget() is settings.centralWidget(), True)
    dismissed = []
    settings.internet.dismiss = lambda: dismissed.append(1)
    settings.internet_close.click()
    chk("closing it hides it for the outage", (settings.internet_bar.isVisible(), dismissed),
        (False, [1]))
    settings.internet.poll = lambda: (net.BACK_MESSAGE, net.BACK_BG)
    settings.refresh_internet_banner(); app.processEvents()
    chk("the green message shows without a close button", (settings.internet_bar.isVisible(),
        settings.internet_close.isVisible()), (True, False))
    settings.internet.poll = lambda: None
    settings.refresh_internet_banner()
    chk("and hides", settings.internet_bar.isVisible(), False)
    settings.internet_warning_chk.setChecked(False)
    chk("saving succeeds", settings.save_settings(show_message=False), True)
    written = configparser.ConfigParser(interpolation=None)
    written.read(SETTINGS_INI_FILE, encoding="utf-8")
    chk("switching it off is written",
        written["Settings"].get(net.ENABLE_KEY), "False")

    # ------------------------------------------------------------------
    # The wifi picker
    # ------------------------------------------------------------------
    from shared import wifi

    print("10. nmcli's terse output is read as nmcli writes it")
    chk("an escaped colon stays in the name", wifi.split_terse("*:Cafe\\:Guest:70:WPA2"),
        ["*", "Cafe:Guest", "70", "WPA2"])
    chk("and an escaped backslash", wifi.split_terse(" :a\\\\b:5:"), [" ", "a\\b", "5", ""])

    def fake(responses, calls=None):
        def runner(args, timeout):
            if calls is not None:
                calls.append(list(args))
            for key, answer in responses.items():
                if key in args:
                    return answer
            return 0, ""
        return runner

    print("11. connected means a wifi or wired connection is up")
    chk("wifi up", wifi.network_connected(fake({"device": (0,
        "wifi:connected\nloopback:connected (externally)\nethernet:unavailable\n")})), True)
    chk("a cable is as good", wifi.network_connected(fake({"device": (0,
        "wifi:disconnected\nethernet:connected\n")})), True)
    chk("nothing up", wifi.network_connected(fake({"device": (0,
        "wifi:disconnected\nloopback:connected (externally)\nethernet:unavailable\n")})), False)
    chk("radio switched off", wifi.network_connected(fake({"device": (0,
        "wifi:unavailable\n")})), False)
    chk("no nmcli to ask is not a reason to nag", wifi.network_connected(fake({"device": (1, "")})),
        None)
    chk("still connecting is not an answer yet", wifi.network_connected(fake({"device": (0,
        "wifi:connecting (getting IP configuration)\nethernet:unavailable\n")})), None)

    print("12. the scan: one row per name, strongest first, hidden networks left out")
    calls = []
    networks = wifi.scan(fake({"list": (0, "*:BOB:80:WPA2 WPA3\n :BOB:55:WPA2 WPA3\n"
                                         " ::90:WPA2\n :Open Cafe:40:\n :Far:20:WPA1\n")}, calls))
    chk("names", [n["ssid"] for n in networks], ["BOB", "Open Cafe", "Far"])
    chk("the stronger BOB kept", networks[0]["signal"], 80)
    chk("an open network is not secure", networks[1]["secure"], False)
    chk("the radio is switched on before scanning", calls[0], ["radio", "wifi", "on"])

    print("13. connecting, and what a failure says")
    calls = []
    chk("a password is passed to nmcli", wifi.connect("BOB", "p&ss word", fake({}, calls)),
        (True, ""))
    chk("exactly as typed", calls[-1], ["device", "wifi", "connect", "BOB", "password",
                                        "p&ss word"])
    wifi.connect("Open Cafe", "", fake({}, calls))
    chk("an open network gets no password", calls[-1], ["device", "wifi", "connect", "Open Cafe"])
    wrong = (4, "Error: Connection activation failed: Secrets were required, but not provided.")
    chk("wrong password", wifi.connect("BOB", "x", fake({"connect": wrong}))[1], wifi.WRONG_PASSWORD)
    chk("not allowed from this session",
        wifi.connect("BOB", "x", fake({"connect": (1, "Error: Not authorized to control networking.")}))[1],
        wifi.NOT_ALLOWED)
    chk("gone", wifi.connect("BOB", "x", fake({"connect": (10, "Error: No network with SSID 'BOB' found.")}))[1],
        wifi.NOT_FOUND)

    print("14. at launch at once; afterwards two minutes, and «later» means ten more")
    watch = wifi.WifiWatch()
    watch.record(False, 0)
    chk("an app started with no network asks straight away", watch.should_prompt(0), True)
    watch = wifi.WifiWatch()
    watch.record(None, 0); watch.record(None, 5)
    chk("not while the boot is still connecting", watch.should_prompt(5), False)
    watch.record(False, 20)
    chk("but at once if that connecting fails", watch.should_prompt(20), True)
    watch = wifi.WifiWatch()
    watch.record(True, 0)
    watch.record(False, 0)
    watch.record(None, 30); watch.record(False, 60); watch.record(None, 90)
    chk("NetworkManager retrying does not restart the wait",
        watch.should_prompt(wifi.PROMPT_AFTER_SECONDS), True)
    watch = wifi.WifiWatch()
    watch.record(True, -1)
    watch.record(False, 0)
    chk("not at 1:59", watch.should_prompt(wifi.PROMPT_AFTER_SECONDS - 1), False)
    chk("at 2:00", watch.should_prompt(wifi.PROMPT_AFTER_SECONDS), True)
    watch.snooze(200)
    chk("put off", watch.should_prompt(201), False)
    chk("back ten minutes later", watch.should_prompt(200 + wifi.SNOOZE_SECONDS), True)
    watch.record(True, 900)
    chk("reconnecting ends it", (watch.should_prompt(901), watch.connected()), (False, True))
    watch.record(None, 950)
    chk("not knowing is not offline", watch.connected(), True)

    print("15. the picker, tapped through")
    import wifi_dialog as wd
    calls = []
    answers = {"list": (0, "*:BOB:80:WPA2\n :Open Cafe:40:\n"), "connect": wrong}
    dialog = wd.WifiDialog(runner=fake(answers, calls))
    dialog.setGeometry(0, 0, 800, 480); dialog.show(); dialog.open_list()
    def wait(condition):
        for _ in range(100):
            app.processEvents()
            if condition():
                return True
            time.sleep(0.02)
        return False
    chk("the networks are listed", wait(lambda: dialog.networks.count() == 2), True)
    dialog.network_tapped(dialog.networks.item(0))
    chk("a secured network asks for its password", dialog.pages.currentIndex(), 1)
    def tap(label):
        app.processEvents()
        keys = [b for b in dialog.keyboard.findChildren(wd.QPushButton)
                if b.isVisible() and b.text() == label]
        keys[0].click()
    tap(wd.SHIFT); tap("H")
    for c in "ome": tap(c)
    tap(wd.TO_SYMBOLS); tap("&&")
    chk("shift is for one letter, symbols type", dialog.password.text(), "Home&")
    amp = [b for b in dialog.keyboard.findChildren(wd.QPushButton) if b.text() == "&&"]
    chk("the & key shows its label", len(amp), 1)
    dialog.connect_tapped()
    chk("connect runs", wait(lambda: not dialog.busy()), True)
    chk("with what was typed", calls[-1][-2:], ["password", "Home&"])
    chk("a wrong password says so and stays", (dialog.password_status.text(),
        dialog.isVisible()), (wifi.WRONG_PASSWORD, True))
    answers["connect"] = (0, "")
    dialog.connect_tapped()
    wait(lambda: not dialog.busy())
    chk("success is said", dialog.password_status.text(), wd.CONNECTED)
    chk("and the picker closes itself", wait(lambda: not dialog.isVisible()), True)
    later = []
    dialog2 = wd.WifiDialog(runner=fake(answers, calls), on_later=lambda: later.append(1))
    dialog2.show(); dialog2.open_list(); wait(lambda: dialog2.networks.count() == 2)
    dialog2.network_tapped(dialog2.networks.item(1))
    wait(lambda: not dialog2.busy())
    chk("an open network connects without asking", calls[-1], ["device", "wifi", "connect", "Open Cafe"])
    dialog2.show(); dialog2.pages.setCurrentIndex(0); dialog2.later()
    chk("«later» closes it and puts it off", (dialog2.isVisible(), later), (False, [1]))

    print("16. the time app opens it after two minutes offline, and closes it on reconnect")
    counter.wifi.watch.down_since = 0
    counter.show_wifi_picker(True); app.processEvents()
    picker = counter.wifi_dialog
    chk("open over the whole window, inside it rather than as a window of its own",
        (picker.isVisible(), picker.isWindow(), picker.geometry() == counter.rect()),
        (True, False, True))
    chk("above the window buttons", counter.children().index(picker)
        > counter.children().index(counter.exit_btn), True)
    counter.setFixedSize(800, 480)
    chk("and every part of it on the screen",
        all(counter.rect().contains(w.mapTo(counter, w.rect().bottomRight()))
            for w in (picker.refresh_btn, picker.networks)), True)
    counter.show_internet_banner((net.OFFLINE_MESSAGE, net.OFFLINE_BG))
    chk("the internet banner keeps off the picker", counter.internet_banner.isVisible(), False)
    counter.wifi.watch.record(True, 10)
    counter.show_wifi_picker(False); app.processEvents()
    chk("closed once back on a network", counter.wifi_dialog.isVisible(), False)
finally:
    with open(SETTINGS_INI_FILE, "w", encoding="utf-8") as f:
        f.write(saved_ini)
    with open(MAP_FILE, "w", encoding="utf-8") as f:
        f.write(saved_map)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
