"""Convert an Aladhan export (api.aladhan.com's calendar, flattened to CSV) to the
Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha table the apps read.

First written on akram's device for lagos-2026.csv. Aladhan already gives each time in
the city's own clock, as "05:36 (WAT)", so the zone suffix is dropped and nothing shifted.

    python3 00_aladhan_convert_csv.py <input.csv> <output.csv>
"""

import csv
import os
import re
import sys
import tempfile

OUTPUT_HEADER = ["Month", "Day", "Fajr", "Sunrise", "Dhuhr", "Asr", "Maghrib", "Isha"]
PRAYER_COLUMNS = ["timings.Fajr", "timings.Sunrise", "timings.Dhuhr",
                  "timings.Asr", "timings.Maghrib", "timings.Isha"]
MONTH_COLUMN = "date.gregorian.month.number"
DAY_COLUMN = "date.gregorian.day"
TIME = re.compile(r"^(\d{1,2}):(\d{2})")


def clock(value):
    """'05:36 (WAT)' -> '05:36'. None when the cell holds no time."""
    match = TIME.match(str(value).strip())
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def rows(input_file):
    with open(input_file, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in PRAYER_COLUMNS + [MONTH_COLUMN, DAY_COLUMN]
                   if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"not an Aladhan export - missing {', '.join(missing)}")
        for line in reader:
            try:
                month, day = int(line[MONTH_COLUMN]), int(line[DAY_COLUMN])
            except (TypeError, ValueError):
                continue
            times = [clock(line[c]) for c in PRAYER_COLUMNS]
            if None in times:
                continue
            yield [str(month), str(day)] + times


def convert(input_file, output_file):
    out = list(rows(input_file))
    if not out:
        raise ValueError(f"no prayer time rows could be parsed from {input_file}")
    # Written beside the destination and moved over it, so a failed conversion never
    # leaves the owner's prayer times file half-written.
    out_dir = os.path.dirname(os.path.abspath(output_file))
    os.makedirs(out_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(OUTPUT_HEADER)
            writer.writerows(out)
        os.replace(tmp_path, output_file)
    except OSError:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return len(out)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 00_aladhan_convert_csv.py <input.csv> <output.csv>")
        sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"Error: {sys.argv[1]} not found.")
        sys.exit(1)
    try:
        count = convert(sys.argv[1], sys.argv[2])
    except (ValueError, OSError, csv.Error) as error:
        print(f"Error: {error}")
        sys.exit(1)
    print(f"Successfully converted {count} rows. Output saved to: \n{sys.argv[2]}")
