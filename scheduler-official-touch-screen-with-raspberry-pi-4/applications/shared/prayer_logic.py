"""Prayer times, periods, and the colour each period is in.

Moved here out of applications/desktop/prayer_times_gui/main.py so the web server can
answer with the same rules the touch screen draws. Nothing in this module imports PyQt,
and nothing in it knows about pixels: period_state returns colour *names*, and each
front end maps those to its own paint.

The caller sets PRAYER_MAP_FILE before the first load_prayer_times(). The GUI points it
at its own copy beside main.py, which apply_settings.sh refreshes; the web server points
it at config/prayer_times_map.py, which is where that copy is generated.
"""

import os
from datetime import datetime, timedelta

# -------------------------
# Build date → prayer map
# -------------------------
# Rebuilt in place rather than rebound, so every reference held elsewhere sees the new
# times: apply_settings.sh rewrites prayer_times_map.py underneath a running app - from
# the Settings GUI and from the new year's cron job - and it restarts the athan service
# but not this one. Without a reload the screen would keep showing the times it was
# started with, for as long as the kiosk stays up.
prayersByDate = {}
PRAYER_MAP_FILE = None
_prayer_map_mtime = None


def load_prayer_times():
    """Re-read the generated map. False if it could not be read this time.

    Read and executed rather than imported: import would answer from the .pyc cache,
    which is judged stale only by the source's size and mtime in whole seconds. Every
    time is HH:MM, so a regenerated map is very often exactly the same size as the one
    before it, and a changed prayer time would be silently ignored. The athan service
    reads the same file the same way."""
    global _prayer_map_mtime
    namespace = {}
    try:
        stamp = os.path.getmtime(PRAYER_MAP_FILE)
        with open(PRAYER_MAP_FILE, encoding="utf-8") as handle:
            exec(handle.read(), {}, namespace)
        rows = namespace["prayerTimes"]
    except (OSError, SyntaxError, ValueError, KeyError, TypeError):
        # cp -f is not atomic, so a read can land mid-write. The old times stay in
        # place and the mtime is left unrecorded, which retries on the next tick.
        return False

    prayersByDate.clear()
    for pt in rows:
        prayersByDate[f"{pt['Month']}-{pt['Day']}"] = {
            "الفجر": pt.get("Fajr"),
            "الشروق": pt.get("Sunrise"),
            "الظهر": pt.get("Dhuhr"),
            "العصر": pt.get("Asr"),
            "المغرب": pt.get("Maghrib"),
            "العشاء": pt.get("Isha"),
        }
    _prayer_map_mtime = stamp
    return True


def prayer_times_changed():
    """True when the generated map has been rewritten since it was last read."""
    try:
        return os.path.getmtime(PRAYER_MAP_FILE) != _prayer_map_mtime
    except (OSError, TypeError):
        return False


prayerOrder = ["الفجر", "الشروق", "الظهر", "العصر", "المغرب", "العشاء"]


def duha_window(now):
    """The stretch from الشروق to الظهر, which this page models as الضحى's own period
    rather than as a plain countdown to the الظهر athan.

    Returns (duha_start, dhuhr) while inside it, otherwise None.
    """
    times = prayersByDate.get(key_for_date(now), {})
    sunrise_str, dhuhr_str = times.get("الشروق"), times.get("الظهر")
    if not sunrise_str or not dhuhr_str:
        return None
    sunrise_dt = build_datetime(now, sunrise_str)
    dhuhr_dt = build_datetime(now, dhuhr_str)
    if not sunrise_dt <= now < dhuhr_dt:
        return None
    return sunrise_dt + timedelta(minutes=DUHA_AFTER_SUNRISE_MINUTES), dhuhr_dt


def prayer_display_name(name):
    """الشروق is neither a صلاة nor has an أذان, so it is the one entry shown bare."""
    return name if name == "الشروق" else f"صلاة {name}"


def key_for_date(d):
    return f"{d.month}-{d.day}"


def build_datetime(date, time_str):
    if not time_str:
        return None
    h, m = map(int, time_str.split(":"))
    return datetime(date.year, date.month, date.day, h, m)


def next_occurrence(prayer, now):
    today_time = prayersByDate.get(key_for_date(now), {}).get(prayer)
    if today_time:
        dt = build_datetime(now, today_time)
        if dt > now:
            return dt
    tomorrow = now + timedelta(days=1)
    tomorrow_time = prayersByDate.get(key_for_date(tomorrow), {}).get(prayer)
    if tomorrow_time:
        return build_datetime(tomorrow, tomorrow_time)
    return None


def prev_occurrence(prayer, now):
    today_time = prayersByDate.get(key_for_date(now), {}).get(prayer)
    if today_time:
        dt = build_datetime(now, today_time)
        if dt <= now:
            return dt
    yesterday = now - timedelta(days=1)
    y_time = prayersByDate.get(key_for_date(yesterday), {}).get(prayer)
    if y_time:
        return build_datetime(yesterday, y_time)
    return None


def get_prev_next_prayer(now):
    prev_p = next_p = None
    prev_t = next_t = None
    for p in prayerOrder:
        nt = next_occurrence(p, now)
        pt = prev_occurrence(p, now)
        if nt and (not next_t or nt < next_t):
            next_p, next_t = p, nt
        if pt and (not prev_t or pt > prev_t):
            prev_p, prev_t = p, pt
    return prev_p, next_p, prev_t, next_t


# -------------------------
# Daily prayer table
# -------------------------
DUHA_AFTER_SUNRISE_MINUTES = 20
# The countdown page is the reference: green for the 20 minutes after an athan, red for
# the 20 minutes before the next one.
PERIOD_EDGE_MINUTES = 20

dailyPrayerOrder = ["الفجر", "الشروق", "الضحى", "الظهر", "العصر", "المغرب", "العشاء"]

# Prayer times read as a 12-hour clock, the way they are spoken. The hour drops its
# leading zero but keeps its column - the pad is a space rather than a zero, so the
# colons stay in line down the list in the monospace face the cards use.
MERIDIEM_AM = "AM"
MERIDIEM_PM = "PM"


def clock_12h(when):
    """A datetime as the clock is read here: " 5:12 AM", "12:18 PM".

    The hour is padded rather than zeroed, so every row comes out the same width and the
    colons stay in a column down the card list. One string rather than two labels: the
    whole of it is left-to-right, so there is no bidi reordering to defend against."""
    mark = MERIDIEM_AM if when.hour < 12 else MERIDIEM_PM
    return f"{when.hour % 12 or 12:>2d}:{when.minute:02d} {mark}"


MAKROOH_LABEL = "مكروه"

# Shown on the countdown through every window that is makrooh for nafl: the stretch from
# sunrise until Duha opens, the zawal before Dhuhr, and the close of Asr. One wording for
# all three - what is discouraged in them is nafl, not one named prayer - so the screen
# says the same thing whenever the same rule applies. The backgrounds still differ, and
# deliberately: orange where makrooh is the whole story, red where an athan is also
# minutes away.
MAKROOH_NAFL_NOTICE = "(الوقت مكروه لصلاة النافلة)"

# Periods whose last PERIOD_EDGE_MINUTES are makrooh for nafl, rather than merely close
# to the next athan: zawal at the end of Duha, and the yellowing sun at the end of Asr.
MAKROOH_AT_PERIOD_END = ("الضحى", "العصر")
# Of those, the ones that keep the plain red anyway, because the counter shows them red
# and the two screens are meant to agree. Maghrib really is minutes away at the close of
# العصر - there the مكروه tag carries the makrooh, and the colour carries the athan.
MAKROOH_KEEPS_RED = ("العصر",)


def daily_times(view_date):
    times = prayersByDate.get(key_for_date(view_date))
    if not times:
        return None
    resolved = {}
    for name in dailyPrayerOrder:
        if name == "الضحى":
            sunrise = resolved.get("الشروق")
            resolved[name] = (sunrise + timedelta(minutes=DUHA_AFTER_SUNRISE_MINUTES)
                              if sunrise else None)
        else:
            resolved[name] = build_datetime(view_date, times.get(name))
    return resolved


def daily_rows(view_date, now, is_today):
    """One entry per prayer: the time shown on the card, plus the period it opens.

    A prayer's period runs until the next prayer starts, so the running period is the
    one the current time falls into - that is the row the page highlights."""
    times = daily_times(view_date)
    if not times:
        return None

    rows = []
    for index, name in enumerate(dailyPrayerOrder):
        if index + 1 < len(dailyPrayerOrder):
            end = times[dailyPrayerOrder[index + 1]]
        else:
            next_day = daily_times(view_date + timedelta(days=1))
            end = next_day["الفجر"] if next_day else None
        rows.append({"name": name, "time": times[name], "start": times[name], "end": end})

    # Isha is the only period that crosses midnight, so between midnight and Fajr the
    # running period is yesterday evening's. The card keeps showing tonight's Isha.
    fajr = times["الفجر"]
    if is_today and fajr and now < fajr:
        yesterday = daily_times(view_date - timedelta(days=1))
        if yesterday and yesterday["العشاء"]:
            rows[-1]["start"] = yesterday["العشاء"]
            rows[-1]["end"] = fajr

    return rows


def period_state(name, start, end, now):
    """Colour of the running period, and whether praying nafl in it is makrooh.

    The makrooh windows are the ones the countdown page also warns about: from sunrise
    until Duha opens, the zawal stretch just before Dhuhr, and the close of Asr. The red
    state on every other period only means the next athan is close - it is not makrooh."""
    # Measured off the timestamps, not off a minute count rounded down from them. The
    # countdown page compares seconds, and rounding here first turned the card red while
    # the counter still read 00:20 - one screen a minute ahead of the other.
    edge = timedelta(minutes=PERIOD_EDGE_MINUTES)
    if name == "الشروق":
        return "makrooh", True
    # Makrooh in their own right, so they take the makrooh colour rather than the red
    # that only means the next athan is near - the same sense the countdown page uses.
    if name in MAKROOH_AT_PERIOD_END and end - now <= edge:
        return ("red" if name in MAKROOH_KEEPS_RED else "makrooh"), True
    if now - start <= edge:
        return "green", False
    if end - now <= edge:
        return "red", False
    return "beige", False


# -------------------------
# The boundaries, for a front end that carries no rules
# -------------------------
# The web pages tick a countdown and colour a row without knowing a single rule: they are
# handed the instants at which the answer changes, and only ask which interval "now" is
# in. period_state above stays the one place those instants are decided - this walks it
# rather than restating it, so the two can never drift.
def period_boundaries(name, start, end):
    """Every instant at which period_state's answer changes, with the answer after it.

    Returns a list of {"from": datetime, "color": str, "makrooh": bool}, in order, the
    first entry starting at `start`. A front end picks the last entry whose "from" is at
    or before now."""
    if start is None or end is None:
        return []

    edge = timedelta(minutes=PERIOD_EDGE_MINUTES)
    # Each edge is sampled on both sides rather than on the side the comparison is
    # thought to fall: period_state's green runs to start+edge inclusive and its red
    # begins at end-edge inclusive, and sampling only on the boundary would return the
    # answer before it and lose the span after. A second either way is enough - the
    # countdown compares whole seconds - and the walk below drops whichever sample
    # turns out to repeat. A short period, where these edges cross, sorts out the same
    # way with no special case.
    tick = timedelta(seconds=1)
    candidates = sorted({start, start + edge, start + edge + tick,
                         end - edge, end - edge + tick})

    spans = []
    for moment in candidates:
        if not start <= moment < end:
            continue
        color, makrooh = period_state(name, start, end, moment)
        if spans and spans[-1]["color"] == color and spans[-1]["makrooh"] == makrooh:
            continue
        spans.append({"from": moment, "color": color, "makrooh": makrooh})
    return spans
