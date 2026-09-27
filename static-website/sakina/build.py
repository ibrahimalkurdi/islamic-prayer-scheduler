#!/usr/bin/env python3
"""Build every city's site into <city>/public/.

    static-website/sakina/build.py            this year and next
    static-website/sakina/build.py --year 2027

A city is a folder here holding city.ini and prayer-times.csv. city.ini's timezone is the
clock the site tells the time in; daylight_saving says whether each year also gets that
timezone's clock changes or the table is used as it is.
prayer-times.csv is a symlink into the device's prayers-config/, so the website and the
devices read one table. public/ is generated, committed by the workflow, and served by
Cloudflare Pages as it stands.

It also writes the devices' web_ui/public_sites.json - which table has which site - so a
device can hand out the app from its own city's site. That file ships in a release, so a
new city reaches the devices with the next one; commit it with the new city's folder.
"""

import argparse
import configparser
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
BUILDER = os.path.join(REPO, "tools", "build_static_site.py")
ICONS = os.path.join(HERE, "icons")
BRAND = "سكينة"
# Read by the device's web server, to offer each device the app from its own city's site.
PUBLIC_SITES = os.path.join(REPO, "scheduler-official-touch-screen-with-raspberry-pi-4",
                            "applications", "services", "web_ui", "public_sites.json")


def cities():
    for name in sorted(os.listdir(HERE)):
        if os.path.isfile(os.path.join(HERE, name, "city.ini")):
            yield name


def place_of(folder, city):
    """The city's name: city.ini's place, or else the prayer table's own file name."""
    table = os.path.realpath(os.path.join(folder, "prayer-times.csv"))
    return city.get("place") or os.path.splitext(os.path.basename(table))[0]


def site_url(name):
    return f"https://sakina-{name}.pages.dev"


def public_sites():
    """{prayer table's file name: its city's site}. A device knows its table by that name
    only - see PRAYER_SOURCE_KEY in the web server."""
    sites = {}
    for name in cities():
        table = os.path.realpath(os.path.join(HERE, name, "prayer-times.csv"))
        sites[os.path.basename(table)] = site_url(name)
    return sites


def write_public_sites():
    with open(PUBLIC_SITES, "w", encoding="utf-8") as handle:
        json.dump(public_sites(), handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def build_city(name, years):
    folder = os.path.join(HERE, name)
    config = configparser.ConfigParser(interpolation=None)
    config.read(os.path.join(folder, "city.ini"), encoding="utf-8")
    city = config["city"]
    table = os.path.join(folder, "prayer-times.csv")
    place = place_of(folder, city)
    command = [sys.executable, BUILDER,
               "--csv", table,
               "--place", place,
               "--app-name", f"{BRAND} - {place}",
               "--clock-zone", city["timezone"],
               "--icons-dir", ICONS,
               "--out", os.path.join(folder, "public")]
    if config.getboolean("city", "daylight_saving"):
        command += ["--timezone", city["timezone"]]
    for year in years:
        command += ["--year", str(year)]
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, action="append",
                        help="a year to bake; repeat for more. Defaults to this year "
                             "and next")
    parser.add_argument("city", nargs="*", help="only these cities (default: all)")
    args = parser.parse_args()
    for name in args.city or cities():
        build_city(name, args.year or [])
    write_public_sites()


if __name__ == "__main__":
    main()
