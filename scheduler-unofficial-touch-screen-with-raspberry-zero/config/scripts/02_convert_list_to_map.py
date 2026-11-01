import calendar
import csv
from datetime import datetime
import json
import os

# Replace with your CSV file path

# Resolved dynamically (not hardcoded) - this is invoked non-elevated from
# apply_settings.sh, so $HOME already matches the real user.
MAIN_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "scheduler")
CONFIG_DIR = os.path.join(MAIN_DIR, "config")

PRAYER_INPUT_CSV_FILE = os.path.join(CONFIG_DIR, "prayer_times.csv")
PRAYER_PYTHON_MAP_FILE = os.path.join(CONFIG_DIR, "prayer_times_map.py")

python_maps = []


with open(PRAYER_INPUT_CSV_FILE, newline='') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        row_map = {
            "Month": int(row["Month"]),
            "Day": int(row["Day"]),
            "Fajr": row["Fajr"],
            "Sunrise": row["Sunrise"],
            "Athkar_elsabah": row["Athkar_elsabah"],
            "Duha": row["Duha"],
            "Dhuhr": row["Dhuhr"],
            "Asr": row["Asr"],
            "Maghrib": row["Maghrib"],
            "Athkar_elmasa": row["Athkar_elmasa"],
            "Isha": row["Isha"],
            "Tahajjud": row["Tahajjud"]
        }
        python_maps.append(row_map)

# The table is keyed by month and day with no year, and the source carries 365 rows -
# so in a leap year the 29th has no times of its own. The countdown falls through to
# the 1st of March and reads a day out, and the audio scheduler, which matches on Month
# and Day, finds nothing at all and stays silent for the whole day.
#
# 28 February stands in for it. At this time of year consecutive days differ by well
# under a minute, and the alternative is a day with no athan on it. Added only in a
# leap year, and only if the source did not already carry the row: outside one the key
# is never looked up, so the file matches the year it was generated for.
if calendar.isleap(datetime.now().year):
    if not any(row["Month"] == 2 and row["Day"] == 29 for row in python_maps):
        feb_28 = next(
            (row for row in python_maps if row["Month"] == 2 and row["Day"] == 28), None)
        if feb_28 is None:
            print("WARNING: leap year but no 28 February row to copy - 29 February "
                  "will have no prayer times")
        else:
            leap_day = dict(feb_28, Day=29)
            python_maps.insert(python_maps.index(feb_28) + 1, leap_day)
            print("Leap year: added 29 February from 28 February's times")

# Write Python map to file
with open(PRAYER_PYTHON_MAP_FILE, "w") as py_file:
    py_file.write("prayerTimes = ")
    py_file.write(json.dumps(python_maps, indent=4))

print(f"Python map saved to {PRAYER_PYTHON_MAP_FILE}")

