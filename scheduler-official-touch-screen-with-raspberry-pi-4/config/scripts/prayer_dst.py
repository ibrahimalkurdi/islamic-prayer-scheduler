#!/usr/bin/env python3
"""Daylight-saving adjustment for the prayer times CSV.

Runs as part of the apply_settings.sh pipeline (so init.sh, "Save & Apply" and the
yearly cron job all trigger it), and is also imported by the Settings GUI to locate
the adjusted file.

The timezone selects DST *rules* only - prayer times themselves always come from the
user's CSV. A source file may already contain DST (many published tables do), so a
naive "+1 hour in summer" would double-apply. Instead the baked-in shifts are detected,
stripped to a standard-time baseline, and the real per-day offset is re-applied from
tzdata. That is idempotent: a file already carrying the correct shifts is left alone.
"""
import csv
import os
import sys
import configparser
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9
    ZoneInfo = None

MAIN_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "scheduler")
CONFIG_DIR = os.path.join(MAIN_DIR, "config")
SETTINGS_INI_FILE = os.path.join(CONFIG_DIR, "config.ini")
INPUT_CSV_FILE = os.path.join(CONFIG_DIR, "input-prayers-time.csv")
DST_DIR = os.path.join(CONFIG_DIR, "prayers-config", "dst")
REFERENCE_CSV_NAME = "إدخال-مواقيت-الصلاة-للمستخدم"

ENABLE_KEY = "enable_daylight_saving"
TIMEZONE_KEY = "daylight_saving_timezone"

TIME_COLUMNS = ["Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]
ANCHOR_COLUMN = "Dhuhr"
# Solar noon drifts about a minute a day, so anything this large is a clock change.
TRANSITION_THRESHOLD_MINUTES = 30


def time_to_minutes(hhmm):
    hours, minutes = hhmm.strip().split(":")
    return int(hours) * 60 + int(minutes)


def minutes_to_time(total):
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def dst_output_path(year, config_dir=None):
    directory = DST_DIR if config_dir is None else os.path.join(config_dir, "prayers-config", "dst")
    return os.path.join(directory, f"{REFERENCE_CSV_NAME}_DST_{year}.csv")


def read_settings(settings_file=SETTINGS_INI_FILE):
    """Returns (enabled, timezone_name)."""
    config = configparser.ConfigParser(interpolation=None)
    config.read(settings_file, encoding="utf-8")
    if "Settings" not in config:
        return False, ""
    section = config["Settings"]
    return section.getboolean(ENABLE_KEY, fallback=False), section.get(TIMEZONE_KEY, "").strip()


def round_to_quarter(minutes):
    return int(round(minutes / 15.0)) * 15


def detect_baked_offsets(rows):
    """Per-row minutes of clock shift already present in the file, expressed relative
    to the file's own standard time (its lowest offset across the year, which also
    makes this correct for southern-hemisphere zones where DST spans January)."""
    offsets = []
    running = 0
    previous = None
    for row in rows:
        current = time_to_minutes(row[ANCHOR_COLUMN])
        if previous is not None:
            delta = current - previous
            if abs(delta) >= TRANSITION_THRESHOLD_MINUTES:
                running += round_to_quarter(delta)
        offsets.append(running)
        previous = current
    baseline = min(offsets)
    return [value - baseline for value in offsets]


def expected_offsets(rows, timezone_name, year):
    """Per-row DST offset the selected zone actually applies that year."""
    zone = ZoneInfo(timezone_name)
    offsets = []
    for row in rows:
        month, day = int(row["Month"]), int(row["Day"])
        try:
            stamp = datetime(year, month, day, 12, 0, tzinfo=zone)
        except ValueError:
            # 29 February in a non-leap year - the day before behaves identically.
            stamp = datetime(year, month, day - 1, 12, 0, tzinfo=zone)
        dst = stamp.dst()
        offsets.append(int(dst.total_seconds() // 60) if dst else 0)
    return offsets


def shift_rows(rows, baked, expected):
    adjusted = []
    wrapped = False
    for row, was, wants in zip(rows, baked, expected):
        new_row = dict(row)
        for column in TIME_COLUMNS:
            if column not in row:
                continue
            total = time_to_minutes(row[column]) - was + wants
            if not 0 <= total < 24 * 60:
                wrapped = True
            new_row[column] = minutes_to_time(total)
        adjusted.append(new_row)
    return adjusted, wrapped


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path, fieldnames, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def main():
    enabled, timezone_name = read_settings()
    if not enabled:
        print("Daylight saving is disabled - leaving prayer times unchanged.")
        return 0

    if ZoneInfo is None:
        print("ERROR: this Python has no zoneinfo module; cannot apply daylight saving.")
        return 1

    if not timezone_name:
        print("ERROR: daylight saving is enabled but no timezone is configured.")
        return 1

    try:
        ZoneInfo(timezone_name)
    except Exception as error:
        print(f"ERROR: unknown timezone '{timezone_name}': {error}")
        return 1

    if not os.path.isfile(INPUT_CSV_FILE):
        print(f"ERROR: {INPUT_CSV_FILE} does not exist.")
        return 1

    rows = load_rows(INPUT_CSV_FILE)
    if not rows:
        print(f"ERROR: {INPUT_CSV_FILE} has no data rows.")
        return 1

    year = datetime.now().year
    baked = detect_baked_offsets(rows)
    wanted = expected_offsets(rows, timezone_name, year)
    output_file = dst_output_path(year)

    if baked == wanted:
        print(f"Prayer times already match {timezone_name} for {year} - no change needed.")
        write_rows(output_file, list(rows[0].keys()), rows)
        return 0

    adjusted, wrapped = shift_rows(rows, baked, wanted)
    fieldnames = list(rows[0].keys())
    write_rows(output_file, fieldnames, adjusted)
    write_rows(INPUT_CSV_FILE, fieldnames, adjusted)

    changed = sum(1 for was, wants in zip(baked, wanted) if was != wants)
    print(f"Applied {timezone_name} daylight saving for {year}: {changed} day(s) adjusted.")
    print(f"Saved to {output_file}")
    if wrapped:
        print("WARNING: some times crossed midnight while shifting; please verify them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
