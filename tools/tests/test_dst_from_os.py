#!/usr/bin/env python3
"""Daylight saving follows the clock's own zone, with nothing to choose - and the city files
say which zone they are for.

prayer_dst.py is run as apply_settings.sh runs it, against a throwaway device, with TZ
standing in for the zone the operating system is on.

    python3 tools/tests/test_dst_from_os.py
"""

import configparser
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "scheduler-official-touch-screen-with-raspberry-pi-4",
                      "config", "scripts", "prayer_dst.py")
YEAR = date.today().year

fails = []


def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok:
        fails.append(name)


HOME = tempfile.mkdtemp(prefix="dst-from-os-")
CONFIG = os.path.join(HOME, "Desktop", "scheduler", "config")
os.makedirs(CONFIG)
INPUT = os.path.join(CONFIG, "input-prayers-time.csv")
INI = os.path.join(CONFIG, "config.ini")
SUMMER, WINTER = date(YEAR, 7, 1), date(YEAR, 1, 15)


def berlin_summer(day):
    """Whether Berlin's clocks are an hour ahead that day: last Sunday of March to the
    last Sunday of October."""
    def last_sunday(month):
        d = date(YEAR, month + 1, 1) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    return last_sunday(3) <= day < last_sunday(10)


def write_table(summer_shift):
    """Dhuhr at 12:00 all year, or at 13:00 on Berlin's summer days."""
    with open(INPUT, "w", newline="", encoding="utf-8") as handle:
        out = csv.writer(handle)
        out.writerow(["Month", "Day", "Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"])
        day = date(YEAR, 1, 1)
        while day.year == YEAR:
            hour = 13 if summer_shift and berlin_summer(day) else 12
            out.writerow([day.month, day.day, "05:00", "06:00", f"{hour}:00", "15:00",
                          "18:00", "20:00"])
            day += timedelta(days=1)


def write_settings(**values):
    parser = configparser.ConfigParser(interpolation=None)
    parser["Settings"] = values
    with open(INI, "w", encoding="utf-8") as handle:
        parser.write(handle)


def run(zone):
    env = {**os.environ, "HOME": HOME, "TZ": zone}
    return subprocess.run([sys.executable, SCRIPT], env=env, capture_output=True, text=True)


def dhuhr(day):
    with open(INPUT, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (int(row["Month"]), int(row["Day"])) == (day.month, day.day):
                return row["Dhuhr"]


try:
    print("1. a table in standard time gets the clock's summer hour")
    write_table(summer_shift=False)
    write_settings()
    result = run("Europe/Berlin")
    chk("it runs", result.returncode, 0)
    chk("summer moves an hour", dhuhr(SUMMER), "13:00")
    chk("winter does not", dhuhr(WINTER), "12:00")

    print("2. a device moved to a zone without daylight saving loses the hour")
    run("Asia/Damascus")
    chk("summer is back to standard time", dhuhr(SUMMER), "12:00")
    chk("winter unchanged", dhuhr(WINTER), "12:00")

    print("3. a table that already matches the clock is left alone")
    write_table(summer_shift=True)
    before = open(INPUT, encoding="utf-8").read()
    run("Europe/Berlin")
    chk("byte for byte", open(INPUT, encoding="utf-8").read(), before)

    print("4. the old choice is ignored: the clock's zone decides")
    write_table(summer_shift=False)
    write_settings(enable_daylight_saving="False", daylight_saving_timezone="Asia/Damascus")
    run("Europe/Berlin")
    chk("Berlin's summer hour, though the old switch was off and named Damascus",
        dhuhr(SUMMER), "13:00")

    print("5. daylight_saving_adjustment = off uses the file as it is")
    write_table(summer_shift=False)
    write_settings(daylight_saving_adjustment="off")
    result = run("Europe/Berlin")
    chk("it runs", result.returncode, 0)
    chk("and changes nothing", dhuhr(SUMMER), "12:00")

    print("6. a zone that cannot be read leaves the times and does not fail the apply")
    write_settings()
    result = run("Nowhere/Atlantis")
    chk("exit 0, so apply_settings.sh carries on", result.returncode, 0)
    chk("saying why", "unknown time zone" in result.stdout, True)
    chk("and nothing moves", dhuhr(SUMMER), "12:00")
    print("7. each city file says which zone it is for, as its public site does")
    presets = os.path.join(REPO, "scheduler-official-touch-screen-with-raspberry-pi-4",
                           "config", "prayers-config")
    zones = configparser.ConfigParser(interpolation=None)
    zones.optionxform = str
    zones.read(os.path.join(presets, "zones.ini"), encoding="utf-8")
    listed = dict(zones["zones"])
    shipped = sorted(n for n in os.listdir(presets) if n.endswith(".csv"))
    chk("every city file that ships is in zones.ini", sorted(listed), shipped)
    sites = os.path.join(REPO, "static-website", "alsakina")
    for city in sorted(os.listdir(sites)):
        ini = os.path.join(sites, city, "city.ini")
        if not os.path.isfile(ini):
            continue
        site = configparser.ConfigParser(interpolation=None)
        site.read(ini, encoding="utf-8")
        name = site["city"]["place"] + ".csv"
        chk(f"{city}: zones.ini gives {name} the site's zone", listed.get(name),
            site["city"]["timezone"])
finally:
    shutil.rmtree(HOME, ignore_errors=True)

print("\n" + ("ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
