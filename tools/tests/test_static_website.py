#!/usr/bin/env python3
"""The public city sites under static-website/sakina/.

Each city is built from a prayer table plus a timezone, once per year, through the same
prayer_dst the devices run. What this holds to account: every year gets its own clock
changes whatever the table has baked in, the output is the daily page alone, the browser
finds the right year's file on either side of New Year, and the city folders point at
tables that exist.

Run from the repo root. The browser half is skipped, not failed, where there is no node.
"""

import configparser
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date as date_cls, timedelta
from zoneinfo import ZoneInfo

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILDER = os.path.join(REPO, "tools", "build_static_site.py")
SAKINA = os.path.join(REPO, "static-website", "sakina")
PRAYERS_CONFIG = os.path.join(REPO, "scheduler-official-touch-screen-with-raspberry-pi-4",
                              "config", "prayers-config")

CHECKS = 0
FAILURES = []


def check(label, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append(f"  {label}\n    got  {got!r}\n    want {want!r}")


def check_true(label, got):
    check(label, bool(got), True)


ROOT = tempfile.mkdtemp(prefix="static-website-test-")

# A table in standard time all year, 366 rows as the real ones are. Dhuhr is 12:00 every
# day, so any 13:00 in the output is daylight saving the build put there.
TABLE = os.path.join(ROOT, "table.csv")
with open(TABLE, "w", newline="", encoding="utf-8") as handle:
    writer = csv.writer(handle)
    writer.writerow(["Month", "Day", "Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"])
    day = date_cls(2024, 1, 1)
    while day.year == 2024:
        writer.writerow([day.month, day.day, "05:00", "06:30", "12:00", "15:00",
                         "18:00", "19:30"])
        day += timedelta(days=1)


def build(out, *extra):
    return subprocess.run([sys.executable, BUILDER, "--csv", TABLE, "--out", out,
                           *extra], capture_output=True, text=True)


def dhuhr(out, year, key):
    days = json.load(open(os.path.join(out, "data", f"{year}.json"), encoding="utf-8"))["days"]
    return next(p["clock"].strip() for p in days[key] if p["name"] == "الظهر")


print("1. every year gets its own clock changes")
OUT = os.path.join(ROOT, "berlin")
result = build(OUT, "--timezone", "Europe/Berlin", "--place", "برلين", "--daily-only",
               "--year", "2026", "--year", "2027")
check("the build runs", result.returncode, 0)
if result.returncode:
    print(result.stdout, result.stderr)
check("one file per year", sorted(os.listdir(os.path.join(OUT, "data"))),
      ["2026.json", "2027.json"])
# 2026 changes on 29 March and 25 October, 2027 on 28 March and 31 October.
for year, key, want in ((2026, "3-28", "12:00 PM"), (2026, "3-29", "1:00 PM"),
                        (2026, "10-24", "1:00 PM"), (2026, "10-25", "12:00 PM"),
                        (2027, "3-27", "12:00 PM"), (2027, "3-28", "1:00 PM"),
                        (2027, "10-30", "1:00 PM"), (2027, "10-31", "12:00 PM")):
    check(f"Berlin Dhuhr {key}-{year}", dhuhr(OUT, year, key), want)
check("29 February is left out of a year without one",
      "2-29" in json.load(open(os.path.join(OUT, "data", "2027.json"),
                               encoding="utf-8"))["days"], False)

print("2. a table with the wrong changes baked in is put right")
# The shape of the real Berlin table: summer time carried on to 1 November.
WRONG = os.path.join(ROOT, "wrong.csv")
with open(TABLE, encoding="utf-8") as source, open(WRONG, "w", encoding="utf-8") as out:
    for line in source:
        cells = line.rstrip("\n").split(",")
        if cells[0] != "Month":
            when = date_cls(2024, int(cells[0]), int(cells[1]))
            if date_cls(2024, 3, 29) <= when < date_cls(2024, 11, 1):
                cells[2:] = [f"{int(c[:2]) + 1:02d}{c[2:]}" for c in cells[2:]]
        out.write(",".join(cells) + "\n")
FIXED = os.path.join(ROOT, "fixed")
result = subprocess.run([sys.executable, BUILDER, "--csv", WRONG, "--timezone",
                         "Europe/Berlin", "--year", "2026", "--out", FIXED],
                        capture_output=True, text=True)
check("the build runs", result.returncode, 0)
check("25 October is back on standard time", dhuhr(FIXED, 2026, "10-25"), "12:00 PM")
check("and 31 October", dhuhr(FIXED, 2026, "10-31"), "12:00 PM")
check("summer is untouched", dhuhr(FIXED, 2026, "7-1"), "1:00 PM")

print("3. a zone without daylight saving is left as it is")
DAMASCUS = os.path.join(ROOT, "damascus")
result = build(DAMASCUS, "--timezone", "Asia/Damascus", "--year", "2026")
check("the build runs", result.returncode, 0)
check("midsummer stays at 12:00", dhuhr(DAMASCUS, 2026, "7-1"), "12:00 PM")
check("an unknown zone is refused",
      build(os.path.join(ROOT, "nowhere"), "--timezone", "Mars/Olympus").returncode != 0,
      True)
AS_IS = os.path.join(ROOT, "as-is")
result = subprocess.run([sys.executable, BUILDER, "--csv", WRONG, "--year", "2026",
                         "--out", AS_IS], capture_output=True, text=True)
check("without a zone the build runs", result.returncode, 0)
check("and the table is used as it stands", dhuhr(AS_IS, 2026, "10-31"), "1:00 PM")

print("4. the daily page, and nothing else")
check("the site root is the daily page",
      'id="rows"' in open(os.path.join(OUT, "index.html"), encoding="utf-8").read(), True)
for page in ("countdown", "daily", "settings"):
    check(f"no {page}/ folder", os.path.exists(os.path.join(OUT, page)), False)
config_js = open(os.path.join(OUT, "static", "config.js"), encoding="utf-8").read()
check_true("data is looked up by year", 'window.DATA = "/data/{year}.json";' in config_js)
check_true("nothing acts on a device", "window.DEVICE = false;" in config_js)
check_true("there is no home page to go back to", "window.HOME = false;" in config_js)
check_true("the city is named", 'window.PLACE = "برلين";' in config_js)
page = open(os.path.join(OUT, "index.html"), encoding="utf-8").read()
check_true("the back link goes when there is no home",
           'if (window.HOME === false) document.querySelector("#back").remove();' in page)
for name in ("app.css", "app.js", "Amiri.ttf", "icon-32.png", "icon-128.png",
             "icon-256.png", "manifest.webmanifest"):
    check_true(f"static/{name} is there", os.path.isfile(os.path.join(OUT, "static", name)))
check("a device's map cannot be baked for two years",
      subprocess.run([sys.executable, BUILDER, "--scheduler-dir", ROOT, "--out",
                      os.path.join(ROOT, "x"), "--year", "2026", "--year", "2027"],
                     capture_output=True).returncode != 0, True)

print("5. the browser finds the right year's file")
if shutil.which("node") is None:
    print("   SKIPPED - no node on this machine")
else:
    script = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const out = process.argv[1];
const fetched = [];
const context = { window: { DATA: "/data/{year}.json", DEVICE: false }, console,
    fetch: async (url) => {
        fetched.push(url);
        const file = path.join(out, url);
        if (url.includes("2031")) return { ok: true, status: 200,
            json: async () => { throw new SyntaxError("<!DOCTYPE html>"); } };
        if (!fs.existsSync(file)) return { ok: false, status: 404, json: async () => ({}) };
        const body = fs.readFileSync(file, "utf8");
        return { ok: true, status: 200, json: async () => JSON.parse(body) };
    } };
vm.createContext(context);
const Site = vm.runInContext(fs.readFileSync(path.join(out, "static", "app.js"), "utf8")
                             + "\n;Site;", context);
(async () => {
    const answer = {};
    answer.dec = (await Site.dayData("2026-12-31")).date;
    answer.jan = (await Site.dayData("2027-01-01")).date;
    answer.again = (await Site.dayData("2027-06-01")).date;
    for (const [label, when] of [["missing", "2030-01-01"], ["html", "2031-01-01"]]) {
        try { await Site.dayData(when); answer[label] = "no error"; }
        catch (e) { answer[label] = e.message; }
    }
    answer.fetched = fetched;
    console.log(JSON.stringify(answer));
})();
"""
    run = subprocess.run(["node", "-e", script, OUT], capture_output=True, text=True)
    if run.returncode:
        print(run.stderr)
    check("node runs", run.returncode, 0)
    answer = json.loads(run.stdout or "{}")
    check("31 December comes from 2026", answer.get("dec"), "2026-12-31")
    check("1 January comes from 2027", answer.get("jan"), "2027-01-01")
    check("each year is fetched once", answer.get("fetched", [])[:3],
          ["/data/2026.json", "/data/2027.json", "/data/2030.json"])
    check("a year not built says so", answer.get("missing"), "لا توجد مواقيت لهذا اليوم")
    check("and so does a host that answers with its own page", answer.get("html"),
          "لا توجد مواقيت لهذا اليوم")

print("6. the city folders")
cities = sorted(name for name in os.listdir(SAKINA)
                if os.path.isfile(os.path.join(SAKINA, name, "city.ini")))
check("damascus, berlin and aachen are there",
      {"damascus", "berlin", "aachen"} <= set(cities), True)
for name in cities:
    folder = os.path.join(SAKINA, name)
    table = os.path.join(folder, "prayer-times.csv")
    check_true(f"{name}: the table is a symlink", os.path.islink(table))
    check_true(f"{name}: into the devices' prayers-config/",
               os.path.dirname(os.path.realpath(table)) == os.path.realpath(PRAYERS_CONFIG))
    check_true(f"{name}: and it resolves", os.path.isfile(table))
    check_true(f"{name}: relative, so it works in any checkout",
               not os.path.isabs(os.readlink(table)))
    config = configparser.ConfigParser(interpolation=None)
    config.read(os.path.join(folder, "city.ini"), encoding="utf-8")
    check_true(f"{name}: has a place", config.get("city", "place", fallback=""))
    try:
        daylight_saving = config.getboolean("city", "daylight_saving")
    except (configparser.Error, ValueError):
        daylight_saving = None
    check_true(f"{name}: says true or false for daylight_saving",
               daylight_saving is not None)
    if daylight_saving:
        try:
            ZoneInfo(config.get("city", "timezone", fallback=""))
            zone_ok = True
        except Exception:
            zone_ok = False
        check_true(f"{name}: has a real timezone for its clock changes", zone_ok)


def changes_clocks(name):
    config = configparser.ConfigParser(interpolation=None)
    config.read(os.path.join(SAKINA, name, "city.ini"), encoding="utf-8")
    return config.getboolean("city", "daylight_saving")


check("berlin and aachen change their clocks, damascus does not",
      [changes_clocks(c) for c in ("berlin", "aachen", "damascus")], [True, True, False])

shutil.rmtree(ROOT, ignore_errors=True)

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)} of {CHECKS} checks)")
    print("\n".join(FAILURES))
    sys.exit(1)
print(f"ALL PASS ({CHECKS} checks)")
