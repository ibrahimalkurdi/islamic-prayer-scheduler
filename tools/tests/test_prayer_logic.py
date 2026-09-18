#!/usr/bin/env python3
"""The prayer period rules, which had no tests before they were shared.

These rules were tuned by eye on the touch screen and are now also what the website
paints, so this pins the behaviour that was shipping at the time of the extraction. Run
it before and after touching applications/shared/prayer_logic.py.
"""

import os
import sys
import tempfile
from datetime import date as date_cls, datetime, timedelta

VARIANT = "scheduler-official-touch-screen-with-raspberry-pi-4"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, VARIANT, "applications"))

from shared import prayer_logic as pl  # noqa: E402

FAILURES = []
CHECKS = 0


def check(label, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"  {label}\n    got  {got!r}\n    want {want!r}")


# A fixed year, so the expected answers below are arithmetic rather than today's CSV.
# Fajr 05:00, Sunrise 06:00, Dhuhr 12:00, Asr 15:00, Maghrib 18:00, Isha 20:00 - which
# puts Duha at 06:20 and leaves every period comfortably longer than the 20-minute edge.
ROWS = []
day = date_cls(2026, 1, 1)
while day.year == 2026:
    ROWS.append({"Month": day.month, "Day": day.day, "Fajr": "05:00",
                 "Sunrise": "06:00", "Dhuhr": "12:00", "Asr": "15:00",
                 "Maghrib": "18:00", "Isha": "20:00"})
    day += timedelta(days=1)

with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                 encoding="utf-8") as handle:
    handle.write("prayerTimes = " + repr(ROWS))
    pl.PRAYER_MAP_FILE = handle.name

assert pl.load_prayer_times(), "fixture map did not load"

TODAY = date_cls(2026, 3, 10)


def at(hh, mm, ss=0, day=TODAY):
    return datetime(day.year, day.month, day.day, hh, mm, ss)


print("1. the day's periods are the seven the screen lists")
rows = pl.daily_rows(TODAY, at(13, 0), True)
check("seven rows", [r["name"] for r in rows], pl.dailyPrayerOrder)
check("Duha opens 20 minutes after sunrise", rows[2]["time"], at(6, 20))
check("Duha's period ends at Dhuhr", rows[2]["end"], at(12, 0))
check("Isha runs to tomorrow's Fajr", rows[6]["end"],
      at(5, 0, day=TODAY + timedelta(days=1)))

print("2. before Fajr the running Isha is last night's")
rows = pl.daily_rows(TODAY, at(2, 0), True)
check("Isha started yesterday evening", rows[6]["start"],
      at(20, 0, day=TODAY - timedelta(days=1)))
check("and runs to this morning's Fajr", rows[6]["end"], at(5, 0))
check("while the card still shows tonight's Isha", rows[6]["time"], at(20, 0))

print("3. a browsed date is not given yesterday's Isha")
other = date_cls(2026, 4, 2)
rows = pl.daily_rows(other, at(2, 0), False)
check("Isha starts on the day shown", rows[6]["start"],
      datetime(2026, 4, 2, 20, 0))

print("4. the colours at each edge")
dhuhr_start, asr_start = at(12, 0), at(15, 0)
cases = [
    ("at the athan", at(12, 0, 0), "green", False),
    ("19 minutes after", at(12, 19, 0), "green", False),
    ("exactly 20 after is still green", at(12, 20, 0), "green", False),
    ("a second later it is not", at(12, 20, 1), "beige", False),
    ("mid period", at(13, 30), "beige", False),
    ("21 minutes before the next athan", at(14, 39, 0), "beige", False),
    ("exactly 20 before turns red", at(14, 40, 0), "red", False),
    ("and stays red", at(14, 59, 59), "red", False),
]
for label, now, color, makrooh in cases:
    check(label, pl.period_state("الظهر", dhuhr_start, asr_start, now),
          (color, makrooh))

print("5. the makrooh windows")
check("الشروق is makrooh throughout",
      pl.period_state("الشروق", at(6, 0), at(6, 20), at(6, 10)),
      ("makrooh", True))
check("الشروق is makrooh even at its very start",
      pl.period_state("الشروق", at(6, 0), at(6, 20), at(6, 0)),
      ("makrooh", True))
check("zawal takes the makrooh colour, not red",
      pl.period_state("الضحى", at(6, 20), at(12, 0), at(11, 45)),
      ("makrooh", True))
check("the close of العصر stays red, and is still makrooh",
      pl.period_state("العصر", at(15, 0), at(18, 0), at(17, 50)),
      ("red", True))
check("العصر's own opening is green and not makrooh",
      pl.period_state("العصر", at(15, 0), at(18, 0), at(15, 5)),
      ("green", False))
check("الضحى's opening is green and not makrooh",
      pl.period_state("الضحى", at(6, 20), at(12, 0), at(6, 30)),
      ("green", False))

print("6. the countdown's own view agrees with the table")
prev_p, next_p, prev_t, next_t = pl.get_prev_next_prayer(at(13, 0))
check("the period in force at 13:00 is الظهر", prev_p, "الظهر")
check("counting down to العصر", next_p, "العصر")
check("from 12:00", prev_t, at(12, 0))
check("to 15:00", next_t, at(15, 0))

prev_p, next_p, prev_t, next_t = pl.get_prev_next_prayer(at(2, 0))
check("at 02:00 the period is yesterday's العشاء", prev_p, "العشاء")
check("starting yesterday evening", prev_t,
      at(20, 0, day=TODAY - timedelta(days=1)))
check("counting down to this morning's الفجر", next_t, at(5, 0))

print("7. الضحى's window")
check("inside it", pl.duha_window(at(9, 0)), (at(6, 20), at(12, 0)))
check("before sunrise there is none", pl.duha_window(at(5, 30)), None)
check("after Dhuhr there is none", pl.duha_window(at(12, 30)), None)
check("at sunrise exactly it has begun", pl.duha_window(at(6, 0)),
      (at(6, 20), at(12, 0)))

print("8. the clock reads as it is spoken")
check("morning", pl.clock_12h(at(5, 12)), " 5:12 AM")
check("afternoon", pl.clock_12h(at(12, 18)), "12:18 PM")
check("midnight is 12, not 0", pl.clock_12h(at(0, 5)), "12:05 AM")
check("evening", pl.clock_12h(at(20, 0)), " 8:00 PM")

print("9. الشروق is the one name shown bare")
check("no صلاة prefix", pl.prayer_display_name("الشروق"), "الشروق")
check("every other name takes it", pl.prayer_display_name("الظهر"), "صلاة الظهر")

print("10. period_boundaries says exactly what period_state says, every second")
# This is what lets the browser carry no rules: it is handed the instants at which the
# answer changes and looks up the interval. If the two ever disagree, the website paints
# a different colour from the touch screen.
rows = pl.daily_rows(TODAY, at(13, 0), True)
mismatches = 0
for row in rows:
    name, start, end = row["name"], row["start"], row["end"]
    spans = pl.period_boundaries(name, start, end)
    check(f"{name} has at least one span", bool(spans), True)
    check(f"{name}'s first span starts with the period", spans[0]["from"], start)

    moment = start
    while moment < end:
        want = pl.period_state(name, start, end, moment)
        span = [s for s in spans if s["from"] <= moment][-1]
        if (span["color"], span["makrooh"]) != want:
            mismatches += 1
            if mismatches <= 3:
                FAILURES.append(
                    f"  {name} at {moment}: table says "
                    f"{(span['color'], span['makrooh'])!r}, rules say {want!r}")
        moment += timedelta(seconds=1)
CHECKS += 1
if mismatches:
    FAILURES.append(f"  {mismatches} second(s) disagree in total")

print("11. a period with no end yields no spans rather than raising")
check("missing end", pl.period_boundaries("الظهر", at(12, 0), None), [])
check("missing start", pl.period_boundaries("الظهر", None, at(15, 0)), [])

print("12. a day the map does not have")
# The map is keyed month-day with no year, so any date in any year finds a row - the CSV
# is a yearly cycle. The one real gap is 29 February against a CSV built for a non-leap
# year, which is what a device will meet every four years.
check("29 February against a 2026 map", pl.daily_rows(date_cls(2028, 2, 29),
                                                      at(13, 0), False), None)
check("and any year's 1 January is found", bool(pl.daily_rows(
    date_cls(1990, 1, 1), at(13, 0), False)), True)

os.unlink(pl.PRAYER_MAP_FILE)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)} of {CHECKS} checks)")
    print("\n".join(FAILURES))
    sys.exit(1)
print(f"ALL PASS ({CHECKS} checks)")
