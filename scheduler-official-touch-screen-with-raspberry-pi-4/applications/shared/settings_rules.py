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


# Athkar Elsabah is either a fixed clock time every day or a number of minutes after Fajr.
# A fixed time is the default: it is what people mean by "after the morning Quran", and
# it does not wander by hours across the year the way Fajr does.
ATHKAR_ELSABAH_MODE_CLOCK = "clock"
ATHKAR_ELSABAH_MODE_AFTER_FAJR = "after_fajr"
ATHKAR_ELSABAH_MODES = (ATHKAR_ELSABAH_MODE_CLOCK, ATHKAR_ELSABAH_MODE_AFTER_FAJR)
DEFAULT_ATHKAR_ELSABAH_MODE = ATHKAR_ELSABAH_MODE_CLOCK
DEFAULT_ATHKAR_ELSABAH_CLOCK = "09:45"


def athkar_elsabah_mode(value):
    """The mode a config value names, or the default for anything else - a device that
    has never saved one, or a hand-edited file."""
    value = str(value or "").strip().lower()
    return value if value in ATHKAR_ELSABAH_MODES else DEFAULT_ATHKAR_ELSABAH_MODE


def athkar_elsabah_clock_outside_fajr_dhuhr(clock_minutes, fajr_minutes, dhuhr_minutes,
                                            clock):
    """A fixed Athkar Elsabah time must land strictly after Fajr and strictly before
    Dhuhr. Checked against today's times, like the minutes-after-Fajr rule above; on the
    days of the year it would not fit, 01_add_fields.py moves it inside. Returns
    (outside, message)."""
    if fajr_minutes < clock_minutes < dhuhr_minutes:
        return False, ""

    return True, (f"وقت أذكار الصباح ({clock(clock_minutes)}) يجب أن يكون بعد "
                  f"صلاة الفجر ({clock(fajr_minutes)}) وقبل "
                  f"صلاة الظهر ({clock(dhuhr_minutes)}).")


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


# ---------------------------------------------------------------------------
# Days of the year a chosen time does not fit
# ---------------------------------------------------------------------------
# Athkar Elsabah and Surat Al-Kahf are one setting applied to every day, but the prayers
# they sit between move across the year. On a day the setting does not fit, the
# scheduler moves it to a minute inside. Settings asks before saving such a value, and
# these find the days and say what will happen on them.

def prayer_year_rows(csv_path):
    """Every row of a Month,Day,... CSV as minutes since midnight, with its month and day."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append({
                "month": int(row["Month"]), "day": int(row["Day"]),
                "fajr": time_to_minutes(row["Fajr"]),
                "sunrise": time_to_minutes(row["Sunrise"]),
                "dhuhr": time_to_minutes(row["Dhuhr"]),
                "asr": time_to_minutes(row["Asr"]),
            })
    return rows


def _first(moves):
    """The day the time moves most - the clearest example to show."""
    return max(moves, key=lambda m: abs(m["moved_to"] - m["wanted"]))


def athkar_elsabah_moves(rows, mode, clock_minutes, after_fajr_minutes):
    """The days Athkar Elsabah would fall on or past Dhuhr, or on or before Fajr, each
    with the time it would have been and the time it plays instead."""
    moves = []
    for r in rows:
        if mode == ATHKAR_ELSABAH_MODE_CLOCK:
            wanted = clock_minutes
            moved_to = min(max(wanted, r["fajr"] + 1), r["dhuhr"] - 1)
        else:
            wanted = r["fajr"] + after_fajr_minutes
            moved_to = r["fajr"] + min(after_fajr_minutes, max(1, r["dhuhr"] - r["fajr"] - 1))
        if moved_to != wanted:
            moves.append({**r, "wanted": wanted, "moved_to": moved_to,
                          "late": wanted > moved_to})
    return moves


def friday_quran_moves(rows, year, position, minutes):
    """The Fridays of `year` Surat Al-Kahf would fall on or past Asr, or on or before
    Sunrise, each with the time it would have been and the time it plays instead."""
    from datetime import date
    moves = []
    for r in rows:
        try:
            day = date(year, r["month"], r["day"])
        except ValueError:
            continue
        if day.weekday() != 4:
            continue
        wanted = r["dhuhr"] - minutes if position == "before" else r["dhuhr"] + minutes
        moved_to = wanted
        if moved_to >= r["asr"]:
            moved_to = r["asr"] - 1
        if moved_to <= r["sunrise"]:
            moved_to = r["sunrise"] + 1
        if moved_to != wanted:
            moves.append({**r, "wanted": wanted, "moved_to": moved_to,
                          "late": wanted > moved_to})
    return moves


MONTHS_AR = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
             "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")


def _move_text(name, chosen, count, days_word, m, prayer, bound, clock):
    where, side = ("بعد", "قبل") if m["late"] else ("قبل", "بعد")
    return (f"{name} ({clock(chosen)}) تأتي {where} {prayer} في {count} {days_word}.\n"
            f"مثال: يوم {m['day']} {MONTHS_AR[m['month'] - 1]}، {prayer} {clock(bound)}.\n"
            f"في هذه الأيام ستُشغَّل {side} {prayer} بدقيقة،\n"
            f"أي الساعة {clock(m['moved_to'])} في هذا المثال.")


def year_moves_message(athkar_moves, friday_moves, clock):
    """The question Settings asks before saving a time that does not fit every day, or ""
    when it fits. `clock` renders minutes the way the caller shows times."""
    parts = []
    if athkar_moves:
        m = _first(athkar_moves)
        prayer, bound = ("الظهر", m["dhuhr"]) if m["late"] else ("الفجر", m["fajr"])
        parts.append(_move_text("أذكار الصباح", m["wanted"], len(athkar_moves),
                                "يومًا من السنة", m, f"صلاة {prayer}", bound, clock))
    if friday_moves:
        m = _first(friday_moves)
        prayer, bound = ("صلاة العصر", m["asr"]) if m["late"] else ("الشروق", m["sunrise"])
        parts.append(_move_text("سورة الكهف", m["wanted"], len(friday_moves),
                                "يوم جمعة من السنة", m, prayer, bound, clock))
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n\nهل تريد ذلك؟"
