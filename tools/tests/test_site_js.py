#!/usr/bin/env python3
"""Does the browser paint what the device decided?

Builds a real static site, works out the right answer in Python with the same
prayer_logic the touch screen uses, and hands both to node so site/app.js can be held to
it. That closes the one gap the Python tests cannot reach: the pages are supposed to carry
no prayer rules at all, and this is what proves the lookup they do instead agrees.

Skipped, not failed, where there is no node - the device does not need one, and this is a
check on the front end rather than on anything that ships.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date as date_cls, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VARIANT = "scheduler-official-touch-screen-with-raspberry-pi-4"
APPLICATIONS = os.path.join(REPO, VARIANT, "applications")
sys.path.insert(0, APPLICATIONS)

from shared import prayer_logic  # noqa: E402

if shutil.which("node") is None:
    print("SKIPPED - no node on this machine")
    sys.exit(0)

YEAR = 2026
SAMPLE = date_cls(YEAR, 3, 10)

ROOT = tempfile.mkdtemp(prefix="site-js-test-")
SCHEDULER = os.path.join(ROOT, "scheduler")
os.makedirs(os.path.join(SCHEDULER, "config", "fonts", "arabic-fonts"))

ROWS = []
day = date_cls(YEAR, 1, 1)
while day.year == YEAR:
    ROWS.append({"Month": day.month, "Day": day.day, "Fajr": "05:00",
                 "Sunrise": "06:00", "Dhuhr": "12:00", "Asr": "15:00",
                 "Maghrib": "18:00", "Isha": "20:00"})
    day += timedelta(days=1)
MAP = os.path.join(SCHEDULER, "config", "prayer_times_map.py")
with open(MAP, "w", encoding="utf-8") as handle:
    handle.write("prayerTimes = " + repr(ROWS))

OUT = os.path.join(ROOT, "site")
build = subprocess.run([sys.executable, os.path.join(REPO, "tools", "build_static_site.py"),
                        "--scheduler-dir", SCHEDULER, "--out", OUT, "--year", str(YEAR)],
                       capture_output=True, text=True)
if build.returncode != 0:
    print("FAILED - the static build did not run")
    print(build.stdout, build.stderr)
    sys.exit(1)

prayer_logic.PRAYER_MAP_FILE = MAP
assert prayer_logic.load_prayer_times()

noon = datetime(SAMPLE.year, SAMPLE.month, SAMPLE.day, 13, 0)
rows = prayer_logic.daily_rows(SAMPLE, noon, False)
key = prayer_logic.key_for_date(SAMPLE)

# Every 30 seconds of every period, with the answer the device would give.
samples = []
for row in rows:
    if not (row["start"] and row["end"]):
        continue
    moment = row["start"]
    while moment < row["end"]:
        color, makrooh = prayer_logic.period_state(row["name"], row["start"],
                                                   row["end"], moment)
        samples.append({"key": key, "name": row["name"],
                        "at": moment.isoformat(timespec="seconds"),
                        "color": color, "makrooh": makrooh})
        moment += timedelta(seconds=30)

clocks = {}
for hour, minute in ((5, 12), (12, 18), (0, 5), (20, 0), (13, 45), (11, 59)):
    when = datetime(SAMPLE.year, SAMPLE.month, SAMPLE.day, hour, minute)
    clocks[when.isoformat(timespec="seconds")] = prayer_logic.clock_12h(when)

# Which period is in force at a few instants, including one inside no period at all.
running = []
for hour, minute in ((5, 30), (6, 10), (9, 0), (13, 0), (16, 0), (19, 0), (21, 0)):
    when = datetime(SAMPLE.year, SAMPLE.month, SAMPLE.day, hour, minute)
    found = None
    for row in rows:
        if row["start"] and row["end"] and row["start"] <= when < row["end"]:
            found = row["name"]
            break
    running.append({"key": key, "at": when.isoformat(timespec="seconds"), "name": found})

# 01:00 on the day after the sample: in a baked year that moment is inside the previous
# day's Isha and inside nothing at all on the day itself, which is why the countdown page
# looks back a day when it finds nothing running.
after_midnight = datetime(SAMPLE.year, SAMPLE.month, SAMPLE.day, 1, 0) + timedelta(days=1)
small_hours = {
    "at": after_midnight.isoformat(timespec="seconds"),
    "todayKey": prayer_logic.key_for_date(after_midnight.date()),
    "yesterdayKey": prayer_logic.key_for_date(after_midnight.date() - timedelta(days=1)),
}

EXPECTED = os.path.join(ROOT, "expected.json")
with open(EXPECTED, "w", encoding="utf-8") as handle:
    json.dump({"samples": samples, "clocks": clocks, "running": running,
               "smallHours": small_hours}, handle, ensure_ascii=False)

result = subprocess.run(["node", os.path.join(REPO, "tools", "tests", "test_site_js.js"),
                         OUT, os.path.join(OUT, "data", "year.json"), EXPECTED],
                        capture_output=True, text=True)
print(result.stdout.strip())
if result.stderr.strip():
    print(result.stderr.strip())

shutil.rmtree(ROOT, ignore_errors=True)
sys.exit(result.returncode)
