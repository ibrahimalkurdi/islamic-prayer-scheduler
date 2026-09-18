"""What the website is told, in JSON.

Kept apart from the serving in main.py because tools/build_static_site.py calls the same
functions to bake a year of days into a file, and because it is what the tests exercise.

The rule that shapes all of this: **no prayer rule and no settings rule lives here.**
day_payload walks applications/shared/prayer_logic and reports the instants at which its
answers change; the browser only asks which interval the clock is in. That is what lets
the same pages be served from a static host with no Python behind them, and what stops
the website and the touch screen ever painting different colours.
"""

import configparser
import os
from datetime import date as date_cls, datetime, time, timedelta

from shared import audio_lists, prayer_logic, settings_rules

# The colours the touch screen paints, by the names period_state returns. Sent to the
# browser rather than written into the CSS so that changing one in the GUI changes the
# website too - the two screens are meant to agree.
#
# The two pages do not share a palette, and neither do they on the device:
# paint_counter_page fills the whole counter flat and draws every label white, while
# PrayerCard.apply_state gives the running card a gradient, a derived border and a glow,
# and leaves the rest of the list dark.
PERIOD_COLORS = {
    "green": "#006600",
    "beige": "#E7DBC1",
    "red": "#990000",
    "makrooh": "#BF360C",
}
PERIOD_TEXT = {
    "green": "#FFFFFF",
    "beige": "#4A3F2F",
    "red": "#FFFFFF",
    "makrooh": "#FFFFFF",
}
COUNTDOWN_BG_DEFAULT = "#333333"

# The counter, as update_countdown chooses its background. Note "beige": period_state
# returns it for the ordinary middle of a period, and the counter has no beige - that
# stretch is COUNTDOWN_BG_DEFAULT, the neutral grey. Text is white on all four, because
# paint_counter_page styles the page's labels white outright.
COUNTDOWN_FILL = {
    "green": "#006600",
    "red": "#990000",
    "makrooh": "#BF360C",
    "beige": COUNTDOWN_BG_DEFAULT,
}
COUNTDOWN_TEXT = "#FFFFFF"

# The daily list's running card, as PrayerCard.apply_state paints it. The derived shades
# are QColor.darker()/lighter() results - written out rather than recomputed here, so the
# web service keeps no Qt dependency. tools/tests/test_web_ui.py re-derives them with a
# real QColor and fails if they have drifted, so these cannot quietly go stale.
#
#   gradient  x1:0 y1:0 x2:1 y2:0, base -> base.darker(112 if lightness > 170 else 128)
#   border    2px base.darker(112) when the fill is light, base.lighter(118) otherwise
#   glow      the base at alpha 90, blur 16, no offset
#
# makrooh is flat on purpose: the gradient would fade the card away from the exact orange
# the counter paints, and those two are meant to match.
CARD_ACTIVE = {
    "green":   {"from": "#006600", "to": "#005000", "border": "#007800",
                "glow": "rgba(0, 102, 0, 0.35)", "text": "#FFFFFF", "flat": False},
    "beige":   {"from": "#e7dbc1", "to": "#cec4ac", "border": "#cec4ac",
                "glow": "rgba(231, 219, 193, 0.35)", "text": "#4A3F2F", "flat": False},
    "red":     {"from": "#990000", "to": "#780000", "border": "#b50000",
                "glow": "rgba(153, 0, 0, 0.35)", "text": "#FFFFFF", "flat": False},
    "makrooh": {"from": "#bf360c", "to": "#bf360c", "border": "#e1400e",
                "glow": "rgba(191, 54, 12, 0.35)", "text": "#FFFFFF", "flat": True},
}

# And the cards that are not running: CARD_BG, CARD_BORDER and NAME_COLOR from the app.
CARD_IDLE = {"background": "#1E293B", "border": "#475569", "text": "#F1F5F9"}

# The pill above the list, showing how long the running period still has to run. Shown
# only while one is running - a browsed date has no badge - and coloured from the same
# base as the card beneath it, but by its own recipe:
#
#   gradient  x1:0 y1:0 x2:1 y2:1 (diagonal, not the card's horizontal),
#             base.lighter(112) -> base.darker(122)
#   border    2px base.lighter(118)
#   glow      the base at alpha 120, blur 26
CARD_BADGE = {
    "green":   {"from": "#007200", "to": "#005400", "border": "#007800",
                "glow": "rgba(0, 102, 0, 0.47)", "text": "#FFFFFF"},
    "beige":   {"from": "#fff3d9", "to": "#bdb49e", "border": "#fff7e7",
                "glow": "rgba(231, 219, 193, 0.47)", "text": "#4A3F2F"},
    "red":     {"from": "#ab0000", "to": "#7d0000", "border": "#b50000",
                "glow": "rgba(153, 0, 0, 0.47)", "text": "#FFFFFF"},
    "makrooh": {"from": "#d63c0d", "to": "#9d2c0a", "border": "#e1400e",
                "glow": "rgba(191, 54, 12, 0.47)", "text": "#FFFFFF"},
}


def _iso(when):
    return when.isoformat(timespec="seconds") if when else None


def day_payload(view_date, now=None):
    """One day, as everything a page needs and nothing it has to reason about.

    Every period carries its own list of spans - the instant each colour begins, and
    whether nafl is makrooh in it. A page picks the last span whose "from" is at or
    before the clock. No page anywhere recomputes a rule.

    `is_today` is worked out here rather than assumed. It is what makes daily_rows treat
    the Isha row as last night's period between midnight and Fajr - the one stretch of
    the day that belongs to the evening before. Passing False for it leaves those hours
    inside no period at all, and the countdown has nothing to count.

    `now` is a parameter so the static build can say which moment it is baking for, and
    so this is testable at an hour other than the one the tests happen to run at.
    """
    now = now or datetime.now()
    rows = prayer_logic.daily_rows(view_date, now, view_date == now.date())
    if not rows:
        return None

    periods = []
    for row in rows:
        spans = prayer_logic.period_boundaries(row["name"], row["start"], row["end"])
        periods.append({
            "name": row["name"],
            "display": prayer_logic.prayer_display_name(row["name"]),
            "time": _iso(row["time"]),
            "clock": prayer_logic.clock_12h(row["time"]) if row["time"] else None,
            "start": _iso(row["start"]),
            "end": _iso(row["end"]),
            "spans": [{"from": _iso(s["from"]), "color": s["color"],
                       "makrooh": s["makrooh"]} for s in spans],
        })

    return {
        "date": view_date.isoformat(),
        "periods": periods,
        "colors": PERIOD_COLORS,
        "text_colors": PERIOD_TEXT,
        "countdown": {"fill": COUNTDOWN_FILL, "text": COUNTDOWN_TEXT,
                      "default": COUNTDOWN_BG_DEFAULT},
        "cards": {"active": CARD_ACTIVE, "idle": CARD_IDLE,
                  "badge": CARD_BADGE},
        "default_color": COUNTDOWN_BG_DEFAULT,
        "makrooh_label": prayer_logic.MAKROOH_LABEL,
        "makrooh_notice": prayer_logic.MAKROOH_NAFL_NOTICE,
    }


def year_payload(year):
    """Every day of one year, for the static build. Keyed "M-D", the same key the
    prayer map itself uses, so a page can look up any date with no server."""
    # Each day is baked as it stands at noon on that day - after Fajr, so no day borrows
    # the evening before it. A baked year has no "today", and the page that reads it
    # falls back to the previous day's table for the hours after midnight; see the
    # countdown page.
    days = {}
    day = date_cls(year, 1, 1)
    while day.year == year:
        payload = day_payload(day, datetime.combine(day, time(12, 0)))
        if payload:
            days[prayer_logic.key_for_date(day)] = payload["periods"]
        day += timedelta(days=1)

    first = date_cls(year, 1, 1)
    sample = day_payload(first, datetime.combine(first, time(12, 0))) or {}
    return {
        "year": year,
        "days": days,
        "colors": PERIOD_COLORS,
        "text_colors": PERIOD_TEXT,
        "countdown": {"fill": COUNTDOWN_FILL, "text": COUNTDOWN_TEXT,
                      "default": COUNTDOWN_BG_DEFAULT},
        "cards": {"active": CARD_ACTIVE, "idle": CARD_IDLE,
                  "badge": CARD_BADGE},
        "default_color": COUNTDOWN_BG_DEFAULT,
        "makrooh_label": sample.get("makrooh_label", prayer_logic.MAKROOH_LABEL),
        "makrooh_notice": sample.get("makrooh_notice",
                                     prayer_logic.MAKROOH_NAFL_NOTICE),
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
# The keys the Settings app writes, with the type each one is. The website offers exactly
# these and refuses anything else, so a POST can never introduce a key that
# apply_settings.sh has never seen.
INT_KEYS = ("tahajjud_time", "duha_time", "athkar_elsabah_time", "athkar_elmasa_time",
            "friday_quran_time")
BOOL_KEYS = ("enable_tahajjud_prayer", "enable_duha_prayer", "enable_listen_to_quran",
             "enable_friday_quran", "enable_athkar_elsabah", "enable_athkar_elmasa",
             "enable_prayer_fajr", "enable_prayer_sunrise", "enable_prayer_dhuhr",
             "enable_prayer_asr", "enable_prayer_maghrib", "enable_prayer_isha",
             "enable_daylight_saving")
TEXT_KEYS = ("listen_to_quran", "friday_quran_position", "daylight_saving_timezone")
# Each audio list is a comma-separated set of file names from one event folder.
AUDIO_KEYS = {
    "quran_audio_checked": "quran",
    "tahajjud_audio_checked": "tahajjud",
    "duha_audio_checked": "duha",
    "athkar_elsabah_audio_checked": "athkar_elsabah",
    "athkar_elmasa_audio_checked": "athkar_elmasa",
    "friday_quran_audio_checked": "friday_quran",
    "fajr_audio_checked": "fajr",
    "sunrise_audio_checked": "shorooq",
    "dhuhr_audio_checked": "dhuhr",
    "asr_audio_checked": "asr",
    "maghrib_audio_checked": "maghrib",
    "isha_audio_checked": "isha",
}

FRIDAY_QURAN_POSITIONS = ("before", "after")


def read_config(ini_path):
    config = configparser.ConfigParser(interpolation=None)
    config.read(ini_path, encoding="utf-8")
    if "Settings" not in config:
        config["Settings"] = {}
    return config


def settings_payload(ini_path, scheduler_dir, desktop_dir):
    """The form's current state, and everything it offers to choose from.

    Read afresh every time rather than cached: the touch screen writes the same file, and
    a stale form would quietly put back a value someone changed at the device."""
    config = read_config(ini_path)
    section = config["Settings"]

    values = {}
    for key in INT_KEYS:
        try:
            values[key] = int(section.get(key, "0") or 0)
        except ValueError:
            values[key] = 0
    for key in BOOL_KEYS:
        values[key] = section.getboolean(key, fallback=False)
    for key in TEXT_KEYS:
        values[key] = section.get(key, "")

    audio = {}
    for key, event in AUDIO_KEYS.items():
        directory = audio_lists.audio_dir(scheduler_dir, event)
        audio[key] = {
            "event": event,
            "available": audio_lists.available_audio(directory),
            "checked": sorted(audio_lists.checked_from_config(section.get(key, ""))),
            "folder_missing": not os.path.isdir(directory),
        }

    return {
        "values": values,
        "audio": audio,
        "csv": csv_sources(scheduler_dir, desktop_dir),
        "times": today_times(scheduler_dir, desktop_dir),
    }


def csv_sources(scheduler_dir, desktop_dir):
    """The prayer-times files already on this device, the way the Settings app lists
    them. No upload: a new file still arrives on the Desktop or on a USB stick."""
    found = []
    prayers_config = os.path.join(scheduler_dir, "config", "prayers-config")
    current = os.path.join(desktop_dir, "إدخال-مواقيت-الصلاة-للمستخدم.csv")

    if os.path.isfile(current):
        found.append({"path": current, "name": os.path.basename(current),
                      "where": "desktop", "format": settings_rules.detect_csv_format(current)})

    if os.path.isdir(prayers_config):
        for fname in sorted(os.listdir(prayers_config)):
            path = os.path.join(prayers_config, fname)
            if os.path.isfile(path) and fname.lower().endswith(".csv"):
                found.append({"path": path, "name": fname, "where": "presets",
                              "format": settings_rules.detect_csv_format(path)})

    return {"current": current if os.path.isfile(current) else None,
            "current_valid": settings_rules.csv_is_valid_prayer_format(current),
            "candidates": found}


def today_times(scheduler_dir, desktop_dir):
    """Today's Fajr/Sunrise/Dhuhr in minutes, which the two rules are checked against.

    None when the CSV cannot be read - the caller reports that rather than validating
    against numbers it invented."""
    current = os.path.join(desktop_dir, "إدخال-مواقيت-الصلاة-للمستخدم.csv")
    try:
        return settings_rules.prayer_minutes_for(current, datetime.now().date())
    except (OSError, ValueError, KeyError):
        return None


# Every message these go into is an Arabic sentence with a time inside it. Left to
# itself the bidi algorithm splits "4:35 AM" in two - the digits are weak, AM is strong
# left-to-right - and lays the halves out right to left, so it reads "AM 4:35". A browser
# does this as readily as Qt does; being told the document is RTL is what causes it, not
# what prevents it. These are the same two marks the Settings app wraps its times in.
LTR_ISOLATE = "\u2066"
POP_ISOLATE = "\u2069"


def minutes_to_clock(minutes):
    """A minutes-since-midnight value as the messages read it, wrapped so the bidi
    algorithm keeps it one left-to-right run. Matches the Settings app's own
    minutes_to_clock; strip the isolates if the text is ever compared rather than shown."""
    hour, minute = divmod(minutes % (24 * 60), 60)
    mark = "AM" if hour < 12 else "PM"
    return f"{LTR_ISOLATE}{hour % 12 or 12}:{minute:02d} {mark}{POP_ISOLATE}"


class Invalid(Exception):
    """A submitted value the Settings app would also have refused."""


def apply_submission(ini_path, scheduler_dir, desktop_dir, submitted):
    """Validate a form submission and write it into config.ini.

    Raises Invalid with the message the touch screen would have shown. Writes nothing
    unless every rule passes, so a refused save leaves the file exactly as it was."""
    config = read_config(ini_path)
    section = config["Settings"]

    unknown = set(submitted) - set(INT_KEYS) - set(BOOL_KEYS) - set(TEXT_KEYS) - set(AUDIO_KEYS)
    if unknown:
        raise Invalid(f"إعداد غير معروف: {', '.join(sorted(unknown))}")

    staged = {}

    for key in INT_KEYS:
        if key not in submitted:
            continue
        try:
            value = int(submitted[key])
        except (TypeError, ValueError):
            raise Invalid(f"قيمة غير صالحة للإعداد {key}")
        if value < 0:
            raise Invalid(f"قيمة غير صالحة للإعداد {key}")
        staged[key] = str(value)

    for key in BOOL_KEYS:
        if key in submitted:
            staged[key] = "True" if _as_bool(submitted[key]) else "False"

    for key in TEXT_KEYS:
        if key not in submitted:
            continue
        value = str(submitted[key] or "")
        if key == "friday_quran_position" and value not in FRIDAY_QURAN_POSITIONS:
            raise Invalid("موضع سورة الكهف غير صالح")
        if key == "listen_to_quran" and value:
            _check_clock(value)
        staged[key] = value

    for key, event in AUDIO_KEYS.items():
        if key not in submitted:
            continue
        names = submitted[key]
        if isinstance(names, str):
            names = [n for n in names.split(",") if n.strip()]
        available = set(audio_lists.available_audio(
            audio_lists.audio_dir(scheduler_dir, event)))
        chosen = [n.strip() for n in names if n.strip()]
        missing = [n for n in chosen if n not in available]
        if missing:
            raise Invalid(f"ملف صوتي غير موجود: {', '.join(missing)}")
        staged[key] = audio_lists.checked_to_config(chosen)

    _check_rules(section, staged, scheduler_dir, desktop_dir)

    for key, value in staged.items():
        section[key] = value

    with open(ini_path, "w", encoding="utf-8") as handle:
        config.write(handle)

    return staged


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "checked")


def _check_clock(value):
    try:
        hour, minute = value.split(":")
        if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            raise ValueError
    except (ValueError, AttributeError):
        raise Invalid("صيغة الوقت غير صالحة، استخدم HH:MM")


def _check_rules(section, staged, scheduler_dir, desktop_dir):
    """The two rules the Settings app enforces, against today's real times.

    Checked on the merged picture - what is being submitted on top of what is already in
    the file - so changing only one half of a pair is still validated against the other.
    """
    times = today_times(scheduler_dir, desktop_dir)
    if times is None:
        # No readable CSV means the Settings app refuses to save at all, for the same
        # reason: there is nothing to validate against.
        raise Invalid("ملف مواقيت الصلاة غير صالح أو غير موجود.\n"
                      "الرجاء اختيار ملف مواقيت الصلاة من تطبيق الإعدادات على الجهاز.")

    def merged(key, default=0):
        if key in staged:
            return int(staged[key])
        try:
            return int(section.get(key, default) or default)
        except ValueError:
            return default

    makrooh, message = settings_rules.duha_time_is_makrooh(
        merged("duha_time"), times["sunrise"], times["dhuhr"])
    if makrooh:
        raise Invalid(message)

    conflicts, message = settings_rules.athkar_elsabah_conflicts_with_dhuhr(
        merged("athkar_elsabah_time"), times["fajr"], times["dhuhr"], minutes_to_clock)
    if conflicts:
        raise Invalid(message)
