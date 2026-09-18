"""What makes a settings value valid, and what to say when it is not.

Moved here out of applications/desktop/scheduler_settings_gui/main.py so the website
refuses exactly what the touch screen refuses, in exactly the same words. The rules
returned (ok, message) rather than popping a QMessageBox themselves: the Settings app
shows the message with arabic_warning, the web server sends it back as JSON.

The wording is the wording that was on the screen when this was split out. Changing a
message here changes it in both places, which is the point.
"""

import csv
import os

EXPECTED_CSV_HEADER = [
    "Month", "Day", "Fajr", "Sunrise",
    "Dhuhr", "Asr", "Maghrib", "Isha"
]

# Duha must clear both makrooh windows: the sun still rising at one end, the zawal at the
# other. Kept as one number because the countdown draws both edges with it too - see
# PERIOD_EDGE_MINUTES and DUHA_AFTER_SUNRISE_MINUTES in prayer_logic.
MAKROOH_EDGE_MINUTES = 20


def duha_time_is_makrooh(minutes_before_dhuhr, sunrise_minutes, dhuhr_minutes):
    """Duha must be at least 20 minutes before Dhuhr and at least 20 minutes after
    sunrise. Returns (is_makrooh, message)."""
    if minutes_before_dhuhr < MAKROOH_EDGE_MINUTES:
        return True, ("هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من "
                      "20 دقيقة من صلاة الظهر")

    if (dhuhr_minutes - minutes_before_dhuhr) <= (sunrise_minutes + MAKROOH_EDGE_MINUTES):
        return True, ("هذا الوقت مكروه لأداء صلاة الضحى، لذا يُرجى اختيار وقت أكبر من "
                      "20 دقيقة بعد طلوع الشمس")

    return False, ""


def athkar_elsabah_conflicts_with_dhuhr(minutes_after_fajr, fajr_minutes, dhuhr_minutes,
                                        clock):
    """Athkar Elsabah must land strictly before Dhuhr. Checked against today's actual
    Fajr/Dhuhr - the same times shown in the label under the spinbox.

    `clock` renders a minutes-since-midnight value the way the caller shows times, so the
    message reads the same on the screen as it does in the browser. Returns
    (conflicts, message)."""
    athkar_time = fajr_minutes + minutes_after_fajr

    if athkar_time < dhuhr_minutes:
        return False, ""

    return True, (f"وقت أذكار الصباح ({clock(athkar_time)}) يجب أن يكون قبل "
                  f"صلاة الظهر ({clock(dhuhr_minutes)}).\n"
                  "الرجاء اختيار عدد دقائق أقل.")


def csv_is_valid_prayer_format(path):
    """Header matches EXPECTED_CSV_HEADER and there's at least one data row."""
    if not os.path.isfile(path):
        return False
    try:
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        if not rows:
            return False
        header = [h.strip() for h in rows[0]]
        if header != EXPECTED_CSV_HEADER:
            return False
        return len(rows) >= 2
    except Exception:
        return False


def detect_csv_format(path):
    """Return 'ready' (already Month,Day,... format), 'al_awail' (raw semicolon
    export, needs 00_al_awail_convert_csv.py), or 'unknown'."""
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                if [h.strip() for h in stripped.split(",")] == EXPECTED_CSV_HEADER:
                    return "ready"
                if stripped.startswith("Date") and ";" in stripped:
                    return "al_awail"
    except Exception:
        pass
    return "unknown"


def version_key(text):
    """Sort key for a version string, so 1.0.10 comes after 1.0.9 rather than before it.

    Tolerant of anything that is not a plain number: an unparseable segment sorts as 0
    rather than raising, because this only ever orders a dropdown.
    """
    parts = []
    for chunk in str(text).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def time_to_minutes(hhmm: str) -> int:
    """Convert HH:MM to minutes since midnight"""
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def prayer_row_for(csv_path, date):
    """The row of a Month,Day,... CSV for one date, as a dict of strings."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if int(row["Month"]) == date.month and int(row["Day"]) == date.day:
                return row

    raise ValueError(f"Prayer times not found for {date.day:02d}/{date.month:02d}")


def prayer_minutes_for(csv_path, date):
    """That row as minutes since midnight, under the lowercase names the callers use."""
    row = prayer_row_for(csv_path, date)
    return {
        "fajr": time_to_minutes(row["Fajr"]),
        "sunrise": time_to_minutes(row["Sunrise"]),
        "dhuhr": time_to_minutes(row["Dhuhr"]),
        "asr": time_to_minutes(row["Asr"]),
        "maghrib": time_to_minutes(row["Maghrib"]),
        "isha": time_to_minutes(row["Isha"]),
    }
