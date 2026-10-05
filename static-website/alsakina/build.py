#!/usr/bin/env python3
"""Build every city's site into <city>/public/.

    static-website/alsakina/build.py            this year and next
    static-website/alsakina/build.py --year 2027

A city is a folder here holding city.ini and prayer-times.csv. city.ini's timezone is the
clock the site tells the time in; daylight_saving says whether each year also gets that
timezone's clock changes or the table is used as it is.
prayer-times.csv is a symlink into the device's prayers-config/, so the website and the
devices read one table. public/ is generated, committed by the workflow, and served by
Cloudflare Pages as it stands.

Every site then gets every other city's years too, so its pages can switch between them
offline - see link_cities in tools/build_static_site.py.

all/ is the site with no city in its name, https://alsakina.pages.dev: all/site.ini's default
city built under the plain name «السكينة», carrying every city like the others, so one
installed app shows any of them.

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
BRAND = "السكينة"
ALL = os.path.join(HERE, "all")
ALL_URL = "https://alsakina.pages.dev"
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
    return f"https://alsakina-{name}.pages.dev"


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


def read_city(folder):
    config = configparser.ConfigParser(interpolation=None)
    config.read(os.path.join(folder, "city.ini"), encoding="utf-8")
    return config


def all_default():
    """The city the site with no city of its own opens on, or None when there is none."""
    config = configparser.ConfigParser(interpolation=None)
    config.read(os.path.join(ALL, "site.ini"), encoding="utf-8")
    name = config.get("site", "default", fallback="")
    return name if name in cities() else None


def build_city(name, years, out=None, app_name=None):
    folder = os.path.join(HERE, name)
    config = read_city(folder)
    city = config["city"]
    table = os.path.join(folder, "prayer-times.csv")
    place = place_of(folder, city)
    command = [sys.executable, BUILDER,
               "--csv", table,
               "--place", place,
               "--app-name", app_name or f"{BRAND} - {place}",
               "--clock-zone", city["timezone"],
               "--icons-dir", ICONS,
               "--out", out or os.path.join(folder, "public")]
    if config.getboolean("city", "daylight_saving"):
        command += ["--timezone", city["timezone"]]
    for year in years:
        command += ["--year", str(year)]
    subprocess.run(command, check=True)


def link_all():
    """Every built city's years into every built city's site. Run over all of them, not
    only the ones just built, so a rebuilt table reaches the other sites as well."""
    sys.path.insert(0, os.path.dirname(BUILDER))
    import build_static_site
    sites = {}
    for name in cities():
        folder = os.path.join(HERE, name)
        if os.path.isdir(os.path.join(folder, "public", "data")):
            city = read_city(folder)["city"]
            sites[name] = (os.path.join(folder, "public"), place_of(folder, city),
                           city["timezone"])
    for name in sites:
        build_static_site.link_cities(sites, name)
    default = all_default()
    if default in sites and os.path.isdir(os.path.join(ALL, "public", "data")):
        _out, place, zone = sites[default]
        build_static_site.link_cities(
            {**sites, default: (os.path.join(ALL, "public"), place, zone)}, default)


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
    default = all_default()
    if default and (not args.city or default in args.city):
        build_city(default, args.year or [], out=os.path.join(ALL, "public"), app_name=BRAND)
    link_all()
    write_public_sites()


if __name__ == "__main__":
    main()
