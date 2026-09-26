#!/usr/bin/env python3
"""Bake the prayer pages into a directory that any static host can serve.

    tools/build_static_site.py --scheduler-dir ~/Desktop/scheduler --out dist/site
    tools/build_static_site.py --csv berlin.csv --timezone Europe/Berlin \\
        --place برلين --daily-only --out public

The pages are the same files the device serves - nothing is rendered in Python, here or
there. What changes is where they get their data: on the device they fetch /api/day, and
here each year is written out ahead of time into data/<year>.json by running the very
same applications/shared/prayer_logic over every date. One source of truth for the
makrooh windows and the colours, and no Python at serve time.

Prayer times come from one of two places:

  * --scheduler-dir: a device tree's prayer_times_map.py, exactly as apply_settings.sh
    left it. That map carries one year's daylight saving, so only that year is baked.
  * --csv: a city's prayer table. With --timezone it is put through
    config/scripts/prayer_dst.py once per year - the step a device runs every January - so
    each year gets that year's clock changes whatever the table itself has baked in.
    Without it the table is used as it stands, as on a device with daylight saving off.

Two things do not come along, because neither means anything away from the Raspberry Pi
they manage:

  * the settings page, which writes that device's config.ini and runs its
    apply_settings.sh
  * the mute button, which silences that device's speaker

The home page is rendered with the settings link removed, and config.js is written with
DEVICE = false, which is what the countdown page reads to drop its mute bar.

--daily-only publishes the daily list alone, as the site's only page.

A note on what this output can and cannot be. A page served over HTTPS cannot talk to
http://<hostname>.local, so a globally hosted copy can show prayer times but can never
be the thing that controls a device. Those stay two deployments of the same front end.
"""

import argparse
import gzip
import html
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import date as date_cls, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VARIANT = "scheduler-official-touch-screen-with-raspberry-pi-4"
VARIANT_DIR = os.path.join(REPO, VARIANT)
APPLICATIONS = os.path.join(VARIANT_DIR, "applications")
WEB_UI = os.path.join(APPLICATIONS, "services", "web_ui")
VERSIONS_FILE = os.path.join(REPO, "VERSIONS.json")

sys.path.insert(0, APPLICATIONS)
sys.path.insert(0, WEB_UI)
sys.path.insert(0, os.path.join(VARIANT_DIR, "config", "scripts"))

from shared import prayer_logic  # noqa: E402
import api  # noqa: E402
import prayer_dst  # noqa: E402

# Left behind, along with anything else that acts on the device.
DEVICE_ONLY = ("settings",)
PAGES = ("countdown", "daily", "settings")

# Mirrors FONTS in the web server: URL name -> member of Amiri.zip.
FONTS = {
    "Amiri.ttf": "Amiri-Regular.ttf",
    "Amiri-Bold.ttf": "Amiri-Bold.ttf",
}
# Mirrors ICONS in the web server, so the two deployments name the same files the same
# way and a page's <link> works unchanged in both.
ICONS = {
    "icon-32.png": "athan-app-icon-32.png",
    "icon-128.png": "athan-app-icon-128.png",
    "icon-256.png": "athan-app-icon-256.png",
}


def map_from_device(scheduler_dir):
    map_file = os.path.join(scheduler_dir, "config", "prayer_times_map.py")
    if not os.path.isfile(map_file):
        raise SystemExit(f"no prayer map at {map_file} - run apply_settings.sh first")
    return map_file


def map_from_csv(csv_path, timezone_name, year, work_dir):
    """The city's table as a prayer map file - with `year`'s daylight saving when a
    timezone is given, as it stands when not."""
    rows = prayer_dst.load_rows(csv_path)
    if not rows:
        raise SystemExit(f"{csv_path} has no data rows")
    adjusted = rows
    if timezone_name:
        baked = prayer_dst.detect_baked_offsets(rows)
        wanted = prayer_dst.expected_offsets(rows, timezone_name, year)
        adjusted, wrapped = prayer_dst.shift_rows(rows, baked, wanted)
        if wrapped:
            raise SystemExit(f"{csv_path}: a time crossed midnight while applying {year}'s "
                             "daylight saving")

    entries = [{"Month": int(row["Month"]), "Day": int(row["Day"]),
                **{column: row[column] for column in prayer_dst.TIME_COLUMNS}}
               for row in adjusted]
    map_file = os.path.join(work_dir, f"prayer_times_map_{year}.py")
    with open(map_file, "w", encoding="utf-8") as handle:
        handle.write("prayerTimes = " + repr(entries) + "\n")
    return map_file


def released_version():
    """The pi4 release the devices are pointed at - what a static copy says it is."""
    try:
        with open(VERSIONS_FILE, encoding="utf-8") as handle:
            entry = json.load(handle).get("pi4", "")
    except (OSError, ValueError):
        return ""
    return entry.get("version", "") if isinstance(entry, dict) else entry


def build(out_dir, maps, assets_dir, place="", daily_only=False, icons_dir=None,
          app_name=""):
    """`maps` is {year: prayer map file}; one data/<year>.json is written per entry."""
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(os.path.join(WEB_UI, "site"), out_dir)

    for name in DEVICE_ONLY:
        shutil.rmtree(os.path.join(out_dir, name), ignore_errors=True)

    if daily_only:
        shutil.move(os.path.join(out_dir, "daily", "index.html"),
                    os.path.join(out_dir, "index.html"))
        for name in PAGES:
            shutil.rmtree(os.path.join(out_dir, name), ignore_errors=True)

    # The pages ask for their assets under /static/, which the device's server maps onto
    # site/. A static host has no such mapping, so the files are put where the pages
    # already look for them.
    static = os.path.join(out_dir, "static")
    os.makedirs(static, exist_ok=True)
    for name in ("app.css", "app.js", "config.js", "manifest.webmanifest"):
        shutil.move(os.path.join(out_dir, name), os.path.join(static, name))

    # The icons live in config/icons/ on a device and are served from there, so copytree
    # above did not bring them. Without this the pages still render, but a phone adding
    # the static copy to its home screen gets a blank glyph - the thing the icons are
    # for. Named as the pages ask for them, not as they are stored. --icons-dir gives a
    # site its own icon, already named as the pages ask for it.
    for url_name, source in ICONS.items():
        if icons_dir:
            path = os.path.join(icons_dir, url_name)
        else:
            path = os.path.join(assets_dir, "config", "icons", source)
        try:
            shutil.copyfile(path, os.path.join(static, url_name))
        except OSError:
            print(f"WARNING: {source} not found - the home-screen icon will be blank")

    for url_name, member in FONTS.items():
        font = read_font(assets_dir, member)
        if font:
            with open(os.path.join(static, url_name), "wb") as out:
                out.write(font)
        else:
            print(f"WARNING: {member} not found - pages will use the fallback font stack")

    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    summary = []
    for year, map_file in sorted(maps.items()):
        prayer_logic.PRAYER_MAP_FILE = map_file
        if not prayer_logic.load_prayer_times():
            raise SystemExit(f"could not read {map_file}")
        payload = api.year_payload(year)
        days_in_year = (date_cls(year + 1, 1, 1) - date_cls(year, 1, 1)).days
        missing = days_in_year - len(payload["days"])
        if missing > 0:
            print(f"note: {missing} date(s) of {year} are not in the prayer table")
        with open(os.path.join(data_dir, f"{year}.json"), "w", encoding="utf-8") as out:
            json.dump(payload, out, ensure_ascii=False, separators=(",", ":"))
        summary.append(f"{len(payload['days'])} days of {year}")

    with open(os.path.join(static, "config.js"), "w", encoding="utf-8") as out:
        out.write(
            "/* Written by tools/build_static_site.py. This copy is served from a static\n"
            "   host, so it reads a baked year rather than a device's API, and offers\n"
            "   nothing that would act on a Raspberry Pi. */\n"
            'window.DATA = "/data/{year}.json";\n'
            "window.DEVICE = false;\n"
            f"window.HOME = {'false' if daily_only else 'true'};\n"
            f"window.PLACE = {json.dumps(place, ensure_ascii=False)};\n"
            f"window.VERSION = {json.dumps(released_version())};\n")

    if not daily_only:
        strip_settings_link(os.path.join(out_dir, "index.html"))
    if app_name:
        name_app(out_dir, app_name)

    size = sum(os.path.getsize(os.path.join(root, f))
               for root, _, files in os.walk(out_dir) for f in files)
    # A year file is mostly repeated timestamps, so what a host actually sends is a
    # fraction of what is on disk. Reported because the raw number looks alarming and is
    # not the number that matters.
    wire = 0
    for year in maps:
        with open(os.path.join(data_dir, f"{year}.json"), "rb") as handle:
            wire = max(wire, len(gzip.compress(handle.read())))
    print(f"{out_dir}: {', '.join(summary)}, {size / 1024:.0f} KB "
          f"(a year is at most {wire / 1024:.0f} KB gzipped over the wire)")
    return out_dir


def read_font(assets_dir, member):
    path = os.path.join(assets_dir, "config", "fonts", "arabic-fonts", "Amiri.zip")
    try:
        with zipfile.ZipFile(path) as bundle:
            return bundle.read(member)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


def name_app(out_dir, app_name):
    """The name under the icon once the site is added to a phone's home screen: Android
    takes it from the manifest, iOS from apple-mobile-web-app-title."""
    manifest_path = os.path.join(out_dir, "static", "manifest.webmanifest")
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["name"] = manifest["short_name"] = app_name
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    meta = f'<meta name="apple-mobile-web-app-title" content="{html.escape(app_name)}">\n'
    for folder, _, files in os.walk(out_dir):
        for name in files:
            if name != "index.html":
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as handle:
                page = handle.read()
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(page.replace("</head>", meta + "</head>", 1))


def strip_settings_link(index_path):
    """The home page is a plain file, so the link is removed from it here rather than
    hidden with CSS - a static copy should not carry a link to a page it does not have."""
    with open(index_path, encoding="utf-8") as handle:
        html = handle.read()
    start = html.find('<a class="tile" href="/settings/"')
    if start == -1:
        return
    end = html.find("</a>", start) + len("</a>\n")
    with open(index_path, "w", encoding="utf-8") as handle:
        handle.write(html[:start] + html[end:])


def main():
    home = os.path.expanduser("~")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scheduler-dir",
                        default=os.path.join(home, "Desktop", "scheduler"),
                        help="the device tree to take prayer times and the font from")
    parser.add_argument("--csv", help="a prayer table to bake instead of a device's map")
    parser.add_argument("--timezone", help="the IANA zone whose clock changes the "
                                           "--csv table gets, e.g. Europe/Berlin; leave "
                                           "out to use the table as it stands")
    parser.add_argument("--place", default="", help="the city's name, shown on the page")
    parser.add_argument("--icons-dir", help="a folder holding icon-32.png, icon-128.png "
                                            "and icon-256.png to use instead of the "
                                            "device's icon")
    parser.add_argument("--app-name", default="",
                        help="the name under the icon on a phone's home screen")
    parser.add_argument("--daily-only", action="store_true",
                        help="publish the daily list alone, as the site's only page")
    parser.add_argument("--out", default=os.path.join(REPO, "dist", "site"))
    parser.add_argument("--year", type=int, action="append",
                        help="a year to bake; repeat for more. Defaults to this year, and "
                             "next year as well for --csv")
    args = parser.parse_args()

    this_year = datetime.now().year
    if args.csv:
        years = args.year or [this_year, this_year + 1]
        with tempfile.TemporaryDirectory() as work_dir:
            maps = {year: map_from_csv(args.csv, args.timezone, year, work_dir)
                    for year in years}
            build(args.out, maps, VARIANT_DIR, args.place, args.daily_only,
                  args.icons_dir, args.app_name)
        return

    years = args.year or [this_year]
    if len(years) > 1:
        parser.error("a device's map holds one year's daylight saving; bake one year "
                     "from it, or use --csv")
    maps = {years[0]: map_from_device(args.scheduler_dir)}
    build(args.out, maps, args.scheduler_dir, args.place, args.daily_only, args.icons_dir,
          args.app_name)


if __name__ == "__main__":
    main()
