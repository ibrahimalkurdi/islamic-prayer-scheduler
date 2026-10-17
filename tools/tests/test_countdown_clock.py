"""The clock on the countdown: 🕒 at the end of the window buttons shows and hides it, looks
pressed while it is up, and the choice outlives a restart. The clock sits top-right, moves
under the internet banner while that is up, and keeps clear of the prayer name and the
makrooh notice.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_countdown_clock.py

SHOT_DIR=<dir> also saves a picture of each state there.
"""
import os, sys, importlib.util
from datetime import datetime

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
APPLICATIONS = os.path.join(SCHEDULER, "applications")
TIME_APP = os.path.join(APPLICATIONS, "desktop/prayer_times_gui/main.py")
SHOT_DIR = os.environ.get("SHOT_DIR")

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


def shot(name):
    if SHOT_DIR:
        os.makedirs(SHOT_DIR, exist_ok=True)
        counter.grab().save(os.path.join(SHOT_DIR, name + ".png"))


from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QRect
app = QApplication(sys.argv)
page = load(TIME_APP, "time_app")
if os.path.exists(page.CLOCK_FLAG_FILE):
    os.remove(page.CLOCK_FLAG_FILE)


def start():
    counter = page.AdhanCounter()
    counter.showNormal(); counter.setFixedSize(800, 480); app.processEvents()
    counter.internet.poll = lambda: None
    counter.wifi.poll = lambda: False
    counter.tick(); app.processEvents()
    return counter


def clock_box():
    return counter.clock.geometry()


def name_ink():
    """Where the widest prayer name would be drawn: centred, at most its width share."""
    widest = round(800 * page.COUNTDOWN_NAME_WIDTH_RATIO)
    name = counter.prayerName.geometry()
    return QRect((800 - widest) // 2, name.top(), widest, name.height())


print("1. off until it is asked for")
counter = start()
button = counter.clock_btn
chk("a sixth window button", button.geometry().left(),
    page.WINDOW_BUTTON_LEFT + 5 * page.WINDOW_BUTTON_PITCH)
chk("with the notice and the banner clear of it",
    button.geometry().right() < page.WINDOW_BUTTONS_RIGHT_EDGE, True)
chk("drawn as the clock", button.text(), page.CLOCK_GLYPH)
chk("not pressed, no clock, nothing kept",
    (button.isChecked(), counter.clock.isVisible(), os.path.exists(page.CLOCK_FLAG_FILE)),
    (False, False, False))
shot("1-off")

print("2. a tap shows it, pressed, top-right, and keeps the choice")
button.click(); app.processEvents()
chk("pressed, with the clock up",
    (button.isChecked(), counter.clock.isVisible()), (True, True))
chk("the pressed look is a style of its own", ":checked" in button.styleSheet(), True)
chk("kept for the next start", os.path.exists(page.CLOCK_FLAG_FILE), True)
box = clock_box()
chk("in the top-right corner",
    (box.top(), box.right()), (page.CLOCK_TOP, 800 - page.CLOCK_MARGIN - 1))
chk("showing the time now, large",
    page.clock_markup(datetime.now(), page.CLOCK_LARGE) == counter.clock.text(), True)
chk("as tall as the large size", box.height(), page.CLOCK_LARGE[0])
chk("and above where the prayer name's ink starts",
    box.bottom() < round(480 * page.COUNTDOWN_NAME_INK_TOP_RATIO), True)
chk("left to right, AM/PM after the digits",
    'dir="ltr"' in counter.clock.text()
    and counter.clock.text().index(":") < counter.clock.text().rindex("M</span>"), True)
chk("wide enough for 12:59 PM", box.width(), page.clock_box_width(page.CLOCK_LARGE))
shot("2-on")

print("3. the makrooh notice keeps its size beside it")
counter.title.setText(page.MAKROOH_NAFL_NOTICE); counter.title.setVisible(True)
left, width = counter.notice_strip()
counter.title.setGeometry(left, page.COUNTDOWN_NOTICE_TOP, width, page.COUNTDOWN_NOTICE_HEIGHT)
counter.title.setFont(page.fit_notice_font(page.MAKROOH_NAFL_NOTICE, width))
app.processEvents()
chk("between the buttons and the clock",
    (counter.title.geometry().left() >= page.WINDOW_BUTTONS_RIGHT_EDGE,
     counter.title.geometry().right() < clock_box().left()), (True, True))
chk("still well above the smallest size",
    counter.title.font().pointSize() >= page.COUNTDOWN_NOTICE_MIN_PT + 3, True)
shot("3-notice")
counter.title.setVisible(False)

print("4. the internet banner takes the top, and the clock moves under it")
from shared import internet_status as net
counter.show_internet_banner((net.OFFLINE_MESSAGE, net.OFFLINE_BG)); app.processEvents()
banner = counter.internet_banner.geometry()
box = clock_box()
chk("the banner is up", counter.internet_banner.isVisible(), True)
chk("the clock is under it, not behind it",
    (box.intersects(banner), box.top() > banner.bottom()), (False, True))
chk("still right-aligned", box.right(), 800 - page.CLOCK_MARGIN - 1)
chk("in its compact size, to fit beside the name",
    (box.height(), page.clock_markup(datetime.now(), page.CLOCK_COMPACT) == counter.clock.text()),
    (page.CLOCK_COMPACT[0], True))
chk("still clear of the prayer name", box.intersects(name_ink()), False)
chk("and above the digits", box.bottom() < round(480 * page.COUNTDOWN_VIEW_TOP_RATIO), True)
shot("4-banner")
counter.show_internet_banner(None); app.processEvents()
chk("back to the top, large, when the banner goes",
    (clock_box().top(), clock_box().height()), (page.CLOCK_TOP, page.CLOCK_LARGE[0]))

print("5. not on the daily list")
counter.toggle_view(); app.processEvents()
chk("neither the clock nor its button",
    (counter.clock.isVisible(), counter.clock_btn.isVisible()), (False, False))
counter.toggle_view(); app.processEvents()
chk("both back with the countdown",
    (counter.clock.isVisible(), counter.clock_btn.isVisible(), counter.clock_btn.isChecked()),
    (True, True, True))

print("6. the choice outlives a restart, and a second tap takes it away")
counter.close()
counter = start()
chk("up again after a restart",
    (counter.clock_btn.isChecked(), counter.clock.isVisible()), (True, True))
counter.clock_btn.click(); app.processEvents()
chk("a tap hides it and forgets it",
    (counter.clock_btn.isChecked(), counter.clock.isVisible(),
     os.path.exists(page.CLOCK_FLAG_FILE)), (False, False, False))
left, width = counter.notice_strip()
chk("the notice has the whole strip again", left + width, 800 - page.INTERNET_BANNER_MARGIN)
counter.close()

print()
if fails:
    print(f"FAILED ({len(fails)}): " + ", ".join(fails))
    sys.exit(1)
print("ALL PASS")
