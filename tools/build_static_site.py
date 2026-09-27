#!/usr/bin/env python3
"""Bake the prayer pages into a directory that any static host can serve.

    tools/build_static_site.py --scheduler-dir ~/Desktop/scheduler --out dist/site
    tools/build_static_site.py --csv berlin.csv --timezone Europe/Berlin \\
        --place برلين --out public

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

The output is two apps from the same pages:

  * /             the daily list, landing page as on the device, and /countdown/.
  * /d/<name>/    the same two and the settings page, as the app a device hands out from
                  its own daily page. Its settings and its countdown's mute talk to
                  http://<name>.local from here (Chrome, on the device's wifi); Safari
                  cannot, and is sent to the device's own pages. The pages are written
                  once, under device/, and _redirects maps every name onto them
                  (Cloudflare Pages and Netlify read it). It has its own manifest and
                  icon, so it installs as an app of its own beside the public one.

The public app has no settings page and no mute: they act on one Raspberry Pi. config.js
is written with DEVICE = false. sw.js keeps every page and baked year on the phone, so
both apps open with no network at all.
"""

import argparse
import gzip
import hashlib
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

# A copy given no --app-name / --device-app-name is named these.
DEFAULT_APP_NAME = "سكينة"
DEFAULT_DEVICE_APP_NAME = "سكينة - جهازي"
# Where the pages of the app a device hands out are written; _redirects serves them at
# /d/<name>/.
OWNER_DIR = "device"
SERVICE_WORKER = os.path.join(REPO, "tools", "static_site_sw.js")
REDIRECTS = f"""/d/:name /d/:name/ 301
/d/:name/ /{OWNER_DIR}/ 200
/d/:name/* /{OWNER_DIR}/:splat 200
"""

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


def build(out_dir, maps, assets_dir, place="", icons_dir=None, app_name="",
          clock_zone="", device_app_name=""):
    """`maps` is {year: prayer map file}; one data/<year>.json is written per entry."""
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(os.path.join(WEB_UI, "site"), out_dir)

    # Settings act on a device, so they go to the app a device hands out only - see
    # write_owner_app - and never to the public root.
    with open(os.path.join(out_dir, "settings", "index.html"), encoding="utf-8") as handle:
        settings_page = handle.read()
    shutil.rmtree(os.path.join(out_dir, "settings"))
    # The daily list is the landing page, as it is on the device.
    shutil.move(os.path.join(out_dir, "daily", "index.html"),
                os.path.join(out_dir, "index.html"))
    shutil.rmtree(os.path.join(out_dir, "daily"))

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
            f"window.PLACE = {json.dumps(place, ensure_ascii=False)};\n"
            f"window.VERSION = {json.dumps(released_version())};\n"
            f"window.TIMEZONE = {json.dumps(clock_zone or None)};\n")

    write_owner_app(out_dir, assets_dir, device_app_name or DEFAULT_DEVICE_APP_NAME,
                    settings_page)
    name_app(os.path.join(out_dir, "static", "manifest.webmanifest"),
             public_pages(out_dir), app_name or DEFAULT_APP_NAME)
    with open(os.path.join(out_dir, "_redirects"), "w", encoding="utf-8") as out:
        out.write(REDIRECTS)
    write_service_worker(out_dir)

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


PUBLIC_PAGES = ("index.html", os.path.join("countdown", "index.html"))
SETTINGS_PAGE = os.path.join("settings", "index.html")


def public_pages(out_dir):
    return [os.path.join(out_dir, page) for page in PUBLIC_PAGES]


def name_app(manifest_path, pages, app_name):
    """The name under the icon once the app is added to a phone's home screen: Android
    takes it from the manifest, iOS from apple-mobile-web-app-title."""
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["name"] = manifest["short_name"] = app_name
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    meta = f'<meta name="apple-mobile-web-app-title" content="{html.escape(app_name)}">\n'
    for path in pages:
        with open(path, encoding="utf-8") as handle:
            page = handle.read()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(page.replace("</head>", meta + "</head>", 1))


def write_owner_app(out_dir, assets_dir, app_name, settings_page):
    """The public pages and the settings page under device/, for /d/<name>/, with their
    own manifest and icon so the app installs apart from the public one.

    Everything that tells the two apps apart is addressed relative to the page, so it
    resolves under /d/<name>/: a relative start_url is read against the manifest's own
    address, which makes every device's app start at its own /d/<name>/ without a file
    per device. The settings icon comes from the path too - see Site.ownerHost."""
    owner = os.path.join(out_dir, OWNER_DIR)
    pages = {}
    for page in PUBLIC_PAGES:
        with open(os.path.join(out_dir, page), encoding="utf-8") as handle:
            pages[page] = handle.read()
    pages[SETTINGS_PAGE] = settings_page
    for page, text in pages.items():
        os.makedirs(os.path.dirname(os.path.join(owner, page)), exist_ok=True)
        text = text.replace('href="/static/manifest.webmanifest"',
                            'href="manifest.webmanifest"')
        for url_name in ICONS:
            text = text.replace(f'href="/static/{url_name}"', f'href="{url_name}"')
        if page != "index.html":
            # countdown/ and settings/ are one level down; their icon links name the
            # files beside the daily page.
            text = text.replace('href="manifest.webmanifest"',
                                'href="../manifest.webmanifest"')
            for url_name in ICONS:
                text = text.replace(f'href="{url_name}"', f'href="../{url_name}"')
        with open(os.path.join(owner, page), "w", encoding="utf-8") as handle:
            handle.write(text)

    with open(os.path.join(out_dir, "static", "manifest.webmanifest"),
              encoding="utf-8") as handle:
        manifest = json.load(handle)
    manifest["start_url"] = manifest["scope"] = "./"
    with open(os.path.join(owner, "manifest.webmanifest"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    name_app(os.path.join(owner, "manifest.webmanifest"),
             [os.path.join(owner, page) for page in pages], app_name)

    # The device's own prayer-app icon, whatever --icons-dir gave the public site: this is
    # the device's app, and it sits on a home screen that may carry the public one too.
    for url_name, source in ICONS.items():
        try:
            shutil.copyfile(os.path.join(assets_dir, "config", "icons", source),
                            os.path.join(owner, url_name))
        except OSError:
            print(f"WARNING: {source} not found - the device app's icon will be blank")


def write_service_worker(out_dir):
    """sw.js, with the list of files it keeps and a version that changes whenever any of
    them does - which is what makes a phone take the new copy."""
    files = []
    digest = hashlib.sha256()
    for root, _, names in sorted(os.walk(out_dir)):
        for name in sorted(names):
            path = os.path.join(root, name)
            relative = os.path.relpath(path, out_dir).replace(os.sep, "/")
            if relative in ("_redirects", "sw.js"):
                continue
            with open(path, "rb") as handle:
                digest.update(relative.encode() + b"\0" + handle.read())
            if relative.endswith("index.html"):
                relative = relative[:-len("index.html")]
            files.append("/" + relative)
    with open(SERVICE_WORKER, encoding="utf-8") as handle:
        worker = handle.read()
    worker = worker.replace("__VERSION__", digest.hexdigest()[:12])
    worker = worker.replace("__FILES__", json.dumps(files, ensure_ascii=False, indent=4))
    with open(os.path.join(out_dir, "sw.js"), "w", encoding="utf-8") as out:
        out.write(worker)


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
                                            "device's icon on the public pages")
    parser.add_argument("--clock-zone", default="",
                        help="the IANA zone the pages tell the time in, so a city's site "
                             "shows that city's time wherever it is opened; leave out to "
                             "use the viewer's own clock")
    parser.add_argument("--app-name", default="",
                        help="the name under the icon on a phone's home screen")
    parser.add_argument("--device-app-name", default="",
                        help="the name under the icon of the app a device hands out")
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
            build(args.out, maps, VARIANT_DIR, args.place, args.icons_dir,
                  args.app_name, args.clock_zone, args.device_app_name)
        return

    years = args.year or [this_year]
    if len(years) > 1:
        parser.error("a device's map holds one year's daylight saving; bake one year "
                     "from it, or use --csv")
    maps = {years[0]: map_from_device(args.scheduler_dir)}
    build(args.out, maps, args.scheduler_dir, args.place, args.icons_dir, args.app_name,
          args.clock_zone, args.device_app_name)


if __name__ == "__main__":
    main()
