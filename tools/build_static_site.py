#!/usr/bin/env python3
"""Bake the prayer pages into a directory that any static host can serve.

    tools/build_static_site.py --scheduler-dir ~/Desktop/scheduler --out dist/site

The pages are the same files the device serves - nothing is rendered in Python, here or
there. What changes is where they get their data: on the device they fetch /api/day, and
here a whole year is written out ahead of time into data/year.json by running the very
same applications/shared/prayer_logic over every date. One source of truth for the
makrooh windows and the colours, and no Python at serve time.

Two things do not come along, because neither means anything away from the Raspberry Pi
they manage:

  * the settings page, which writes that device's config.ini and runs its
    apply_settings.sh
  * the mute button, which silences that device's speaker

The home page is rendered with the settings link removed, and config.js is written with
DEVICE = false, which is what the countdown page reads to drop its mute bar.

A note on what this output can and cannot be. The prayer times baked in are the ones on
the device this was built from - one city. And a page served over HTTPS cannot talk to
http://<hostname>.local, so a globally hosted copy can show prayer times but can never
be the thing that controls a device. Those stay two deployments of the same front end.
"""

import argparse
import gzip
import json
import os
import shutil
import sys
import zipfile
from datetime import date as date_cls, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VARIANT = "scheduler-official-touch-screen-with-raspberry-pi-4"
APPLICATIONS = os.path.join(REPO, VARIANT, "applications")
WEB_UI = os.path.join(APPLICATIONS, "services", "web_ui")

sys.path.insert(0, APPLICATIONS)
sys.path.insert(0, WEB_UI)

from shared import prayer_logic  # noqa: E402
import api  # noqa: E402

# Left behind, along with anything else that acts on the device.
DEVICE_ONLY = ("settings",)

FONT_MEMBER = "Amiri-Regular.ttf"
# Mirrors ICONS in the web server, so the two deployments name the same files the same
# way and a page's <link> works unchanged in both.
ICONS = {
    "icon-32.png": "athan-app-icon-32.png",
    "icon-128.png": "athan-app-icon-128.png",
    "icon-256.png": "athan-app-icon-256.png",
}


def build(scheduler_dir, out_dir, year):
    map_file = os.path.join(scheduler_dir, "config", "prayer_times_map.py")
    if not os.path.isfile(map_file):
        raise SystemExit(f"no prayer map at {map_file} - run apply_settings.sh first")

    prayer_logic.PRAYER_MAP_FILE = map_file
    if not prayer_logic.load_prayer_times():
        raise SystemExit(f"could not read {map_file}")

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(os.path.join(WEB_UI, "site"), out_dir)

    for name in DEVICE_ONLY:
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
    # for. Named as the pages ask for them, not as they are stored.
    for url_name, source in ICONS.items():
        path = os.path.join(scheduler_dir, "config", "icons", source)
        try:
            shutil.copyfile(path, os.path.join(static, url_name))
        except OSError:
            print(f"WARNING: {source} not found - the home-screen icon will be blank")

    font = read_font(scheduler_dir)
    if font:
        with open(os.path.join(static, FONT_MEMBER.replace("-Regular", "")), "wb") as out:
            out.write(font)
    else:
        print("WARNING: Amiri.zip not found - pages will use the fallback font stack")

    payload = api.year_payload(year)
    days_in_year = (date_cls(year + 1, 1, 1) - date_cls(year, 1, 1)).days
    missing = days_in_year - len(payload["days"])
    data_dir = os.path.join(out_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "year.json"), "w", encoding="utf-8") as out:
        json.dump(payload, out, ensure_ascii=False, separators=(",", ":"))

    with open(os.path.join(static, "config.js"), "w", encoding="utf-8") as out:
        out.write(
            "/* Written by tools/build_static_site.py. This copy is served from a static\n"
            "   host, so it reads a baked year rather than a device's API, and offers\n"
            "   nothing that would act on a Raspberry Pi. */\n"
            f'window.DATA = "/data/year.json";\n'
            "window.DEVICE = false;\n")

    strip_settings_link(os.path.join(out_dir, "index.html"))

    size = sum(os.path.getsize(os.path.join(root, f))
               for root, _, files in os.walk(out_dir) for f in files)
    # The year file is mostly repeated timestamps, so what a host actually sends is a
    # fraction of what is on disk. Reported because the raw number looks alarming and is
    # not the number that matters.
    with open(os.path.join(data_dir, "year.json"), "rb") as handle:
        wire = len(gzip.compress(handle.read()))
    print(f"{out_dir}: {len(payload['days'])} days of {year}, {size / 1024:.0f} KB "
          f"({wire / 1024:.0f} KB of that gzipped over the wire)")
    if missing > 0:
        print(f"note: {missing} date(s) of the year are not in this device's CSV")
    return out_dir


def read_font(scheduler_dir):
    path = os.path.join(scheduler_dir, "config", "fonts", "arabic-fonts", "Amiri.zip")
    try:
        with zipfile.ZipFile(path) as bundle:
            return bundle.read(FONT_MEMBER)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None


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
    parser.add_argument("--out", default=os.path.join(REPO, "dist", "site"))
    parser.add_argument("--year", type=int, default=datetime.now().year)
    args = parser.parse_args()
    build(args.scheduler_dir, args.out, args.year)


if __name__ == "__main__":
    main()
