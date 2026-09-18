"""The makrooh windows, on both screens that show them.

Nafl is makrooh at three points in the day: from sunrise until Duha opens, at zawal just
before Dhuhr, and as Asr closes. The countdown screen says so in a line of text; the daily
list says so with a tag and the makrooh colour. All three windows are worded the same,
because the rule is the same in all three. The backgrounds are not: Asr keeps the red on
the countdown, because Maghrib really is minutes away and the notice carries the makrooh.

Run from inside the fixture, not from the repo - HOME is resolved from this file's own
directory:

    bash tools/tests/make_fixture.sh
    python3 /tmp/scheduler-update-test/test_makrooh.py
"""
import os, sys, importlib.util
from datetime import datetime, date, timedelta

os.environ["QT_QPA_PLATFORM"] = "offscreen"
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["HOME"] = os.path.join(HERE, "dev")
os.environ["DEVICE_MODEL_FILE"] = os.path.join(HERE, "fake_model")

SCHEDULER = os.path.join(os.environ["HOME"], "Desktop/scheduler")
PRAYER_GUI = os.path.join(SCHEDULER, "applications/desktop/prayer_times_gui/main.py")

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)

spec = importlib.util.spec_from_file_location("prayer_page", PRAYER_GUI)
page = importlib.util.module_from_spec(spec); spec.loader.exec_module(page)

TODAY = date.today()
TIMES = {"Fajr": "04:33", "Sunrise": "06:28", "Dhuhr": "13:08",
         "Asr": "16:38", "Maghrib": "19:38", "Isha": "21:17"}


def at(hour, minute):
    return datetime(TODAY.year, TODAY.month, TODAY.day, hour, minute)


# ---------------------------------------------------------------------------
# The daily list
# ---------------------------------------------------------------------------
print("1. Asr closes makrooh, and only in its last 20 minutes")
ASR, MAGHRIB = at(16, 38), at(19, 38)
chk("21 minutes out nothing has started yet",
    page.period_state("العصر", ASR, MAGHRIB, MAGHRIB - timedelta(minutes=21)), ("beige", False))
chk("20 minutes out it is makrooh, and red",
    page.period_state("العصر", ASR, MAGHRIB, MAGHRIB - timedelta(minutes=20)), ("red", True))
chk("and still so a minute before Maghrib",
    page.period_state("العصر", ASR, MAGHRIB, MAGHRIB - timedelta(minutes=1)), ("red", True))
chk("the middle of the period is untouched",
    page.period_state("العصر", ASR, MAGHRIB, at(17, 30)), ("beige", False))
chk("and it still opens green",
    page.period_state("العصر", ASR, MAGHRIB, ASR + timedelta(minutes=5)), ("green", False))
# The red window and the makrooh window are the same 20 minutes. The card keeps the red,
# because the counter shows that window red and the two screens are meant to agree; the
# مكروه tag beside the time is what says makrooh here.
states = {page.period_state("العصر", ASR, MAGHRIB, MAGHRIB - timedelta(minutes=m))
          for m in range(1, 21)}
chk("the whole window is red, and tagged makrooh", states, {("red", True)})

print("2. the windows that were already makrooh still are")
SUNRISE, DUHA = at(6, 28), at(6, 48)
chk("sunrise, for its whole period",
    page.period_state("الشروق", SUNRISE, DUHA, at(6, 35)), ("makrooh", True))
DHUHR = at(13, 8)
chk("zawal, in Duha's last 20 minutes",
    page.period_state("الضحى", DUHA, DHUHR, DHUHR - timedelta(minutes=10)), ("makrooh", True))
chk("and it is the counter's own orange, not a card-only shade",
    page.PERIOD_COLORS["makrooh"], page.COUNTDOWN_BG_MAKROOH)
chk("but not Duha in the middle",
    page.period_state("الضحى", DUHA, DHUHR, at(10, 0)), ("beige", False))

print("3. no other period turned makrooh")
# The tag is what separates the close of العصر from any other red window - both are red.
chk("العصر closing is tagged", page.period_state(
    "العصر", ASR, MAGHRIB, MAGHRIB - timedelta(minutes=10))[1], True)
ISHA = at(21, 17)
chk("Maghrib's last 20 minutes are red and carry no tag",
    page.period_state("المغرب", MAGHRIB, ISHA, ISHA - timedelta(minutes=10)), ("red", False))
FAJR = at(4, 33)
chk("and so are Fajr's",
    page.period_state("الفجر", FAJR, SUNRISE, SUNRISE - timedelta(minutes=10)), ("red", False))


# ---------------------------------------------------------------------------
# The countdown screen
# ---------------------------------------------------------------------------
print("4. the countdown names it, and stays red while it does")
MAP_FILE = os.path.join(HERE, "makrooh_map.py")
open(MAP_FILE, "w", encoding="utf-8").write(
    "prayerTimes = [\n" + ",\n".join(
        '{"Month": %d, "Day": %d, "Fajr": "%s", "Sunrise": "%s", "Dhuhr": "%s",'
        ' "Asr": "%s", "Maghrib": "%s", "Isha": "%s"}'
        % ((TODAY + timedelta(days=d)).month, (TODAY + timedelta(days=d)).day,
           TIMES["Fajr"], TIMES["Sunrise"], TIMES["Dhuhr"],
           TIMES["Asr"], TIMES["Maghrib"], TIMES["Isha"])
        for d in (-1, 0, 1)) + "\n]\n")
# The map lives in shared.prayer_logic now, and assigning the old name here would be a
# silent no-op - a new attribute nothing reads, which is how this test once passed while
# measuring the device fixture's times instead of its own.
page.prayer_logic.PRAYER_MAP_FILE = MAP_FILE
page.load_prayer_times()

loaded = page.prayer_logic.prayersByDate[page.key_for_date(TODAY)]
chk("the countdown is reading the times written just above",
    loaded["الظهر"], TIMES["Dhuhr"])

real_datetime = page.datetime


class frozen(real_datetime):
    """update_countdown reads the clock itself, so the clock is what gets replaced."""
    fixed = None
    @classmethod
    def now(cls, tz=None):
        return cls.fixed


page.datetime = frozen
frozen.fixed = at(17, 30)     # the window reads the clock while it is being built
window = page.AdhanCounter()


def screen_at(when):
    """The notice, whether it is on screen, the background, and the prayer name."""
    frozen.fixed = when
    window.update_countdown()
    sheet = window.counter_page.styleSheet()
    background = sheet.split("background:")[1].split(";")[0].strip()
    return (window.title.text(), window.title.isVisible(),
            background, window.prayerName.text())


NOTICE = "(الوقت مكروه لصلاة النافلة)"

text, shown, bg, name = screen_at(MAGHRIB - timedelta(minutes=10))
chk("ten minutes before Maghrib the notice is up", text, NOTICE)
chk("worded for nafl, not for a named prayer", "النافلة" in text, True)
chk("and it is actually on screen", shown, True)
# "keep everything as is" - the red stays red, and the row still names the period.
chk("the background is still red", bg, page.COUNTDOWN_BG_RED)
chk("not the makrooh orange the زوال window uses", bg == page.COUNTDOWN_BG_MAKROOH, False)
chk("and the prayer name is untouched", name, page.prayer_display_name("العصر"))

text, shown, bg, _ = screen_at(MAGHRIB - timedelta(minutes=25))
chk("twenty-five minutes out, before red, there is no notice", text, "")
chk("nothing is left on screen", shown, False)
chk("and the background has not gone red yet", bg, page.COUNTDOWN_BG_DEFAULT)

text, _, _, _ = screen_at(at(17, 30))
chk("and none in the middle of the period", text, "")

print("5. no other prayer's red window picked the notice up")
text, _, bg, _ = screen_at(ISHA - timedelta(minutes=10))
chk("Maghrib closing is silent", text, "")
chk("but still red", bg, page.COUNTDOWN_BG_RED)
text, _, bg, _ = screen_at(SUNRISE - timedelta(minutes=10))
chk("Fajr closing is silent", text, "")
chk("and red too", bg, page.COUNTDOWN_BG_RED)

print("6. the sunrise and zawal windows say the same thing, on the same orange")
# One wording for every window that is makrooh for nafl - the rule is the same in all
# three, so the screen should not name a different prayer in each. The backgrounds still
# differ on purpose and are asserted here so a colour change cannot slip through with it.
text, _, bg, _ = screen_at(at(6, 35))
chk("sunrise says nafl, not الضحى", text, NOTICE)
chk("on the makrooh orange, as before", bg, page.COUNTDOWN_BG_MAKROOH)
text, _, bg, _ = screen_at(DHUHR - timedelta(minutes=10))
chk("zawal says nafl too", text, NOTICE)
chk("orange there as well", bg, page.COUNTDOWN_BG_MAKROOH)

print("7. all three windows are worded identically")
windows = {screen_at(at(6, 35))[0],                        # sunrise until الضحى opens
           screen_at(DHUHR - timedelta(minutes=10))[0],    # zawal
           screen_at(MAGHRIB - timedelta(minutes=10))[0]}  # the close of العصر
chk("one notice for all of them", windows, {NOTICE})
chk("and no window still names a prayer", any("الضحى" in t for t in windows), False)

print("8. the card palette and the counter's are the same palette")
# "the daily list should match the countdown" - so these are not two tables that happen
# to agree today, they are one set of values read from both screens.
for state, counter in (("makrooh", page.COUNTDOWN_BG_MAKROOH),
                       ("red", page.COUNTDOWN_BG_RED),
                       ("green", page.COUNTDOWN_BG_GREEN)):
    chk(f"{state} is one colour on both screens", page.PERIOD_COLORS[state], counter)

print("9. both screens change colour on the same second")
# The daily card used to be computed from a minute count floored out of the timestamps,
# so it went red while the counter still read 00:20 and stayed green a minute short at the
# other end. Walked a second at a time across both edges, because that is the only place
# the two ever disagreed.
BY_BACKGROUND = {page.COUNTDOWN_BG_DEFAULT: "beige",
                 page.COUNTDOWN_BG_GREEN: "green",
                 page.COUNTDOWN_BG_RED: "red",
                 page.COUNTDOWN_BG_MAKROOH: "makrooh"}

def both(when):
    """What the counter paints, and what the card would paint, at the same instant."""
    return (BY_BACKGROUND[screen_at(when)[2]],
            page.period_state("المغرب", MAGHRIB, ISHA, when)[0])

EDGE = page.PERIOD_EDGE_MINUTES * 60
for offset in range(EDGE - 5, EDGE + 6):        # the red edge, second by second
    when = ISHA - timedelta(seconds=offset)
    counter, card = both(when)
    chk(f"{offset}s before المغرب's end", card, counter)
for offset in range(EDGE - 5, EDGE + 6):        # and the green one
    when = MAGHRIB + timedelta(seconds=offset)
    counter, card = both(when)
    chk(f"{offset}s after المغرب", card, counter)

# The digits on screen are floored seconds, so the flip has to land where the counter
# still shows 00:20 - not a minute earlier, which is what was reported.
chk("at 00:20 on the clock the card has not gone red",
    page.period_state("المغرب", MAGHRIB, ISHA, ISHA - timedelta(seconds=EDGE + 40))[0], "beige")
chk("and the counter agrees it still reads 00:20",
    screen_at(ISHA - timedelta(seconds=EDGE + 40))[2], page.COUNTDOWN_BG_DEFAULT)

page.datetime = real_datetime
os.remove(MAP_FILE)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
