"""What «إعادة ضبط الإعدادات» puts back, on the touch screen and on the website alike.

The shipped config/default-config.ini wins over the constants here; the constants are
what a device without that file falls back to, as it did before the file shipped.
"""

import configparser

from shared import audio_lists, internet_status, prayer_source
from shared.settings_rules import DEFAULT_ATHKAR_ELSABAH_CLOCK, DEFAULT_ATHKAR_ELSABAH_MODE

DEFAULTS_INT = {
    "tahajjud_time": 20,
    "duha_time": 60,
    "athkar_elsabah_time": 210,
    "athkar_elmasa_time": 20,
    "friday_quran_time": 60,
}

DEFAULTS_BOOL = {
    "enable_tahajjud_prayer": True,
    "enable_duha_prayer": True,
    "enable_listen_to_quran": True,
    "enable_athkar_elsabah": True,
    "enable_athkar_elmasa": True,
    "enable_friday_quran": True,
    internet_status.ENABLE_KEY: internet_status.DEFAULT_ENABLED,
}

DEFAULT_CRON = "07:00"
DEFAULT_FRIDAY_QURAN_POSITION = "after"

# The daylight-saving choice of earlier releases, now the clock's own zone. Not put back
# by a reset even when an older defaults file still names it.
RETIRED_KEYS = ("enable_daylight_saving", "daylight_saving_timezone")

# The prayer-times file is not a setting a reset touches: the file on the Desktop stays,
# and so does the record of where it came from.
KEPT_ON_RESET = (prayer_source.SOURCE_LABEL_KEY, prayer_source.HASH_KEY)


def read_default_settings(path):
    """The [Settings] of the shipped defaults file, or {} when it is missing or unreadable."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error as error:
        print("Failed to read the default settings:", error)
        return {}
    return dict(parser["Settings"]) if parser.has_section("Settings") else {}


def reset_values(current, default_settings_file):
    """The whole [Settings] section after a reset, audio lists aside - see reset_audio."""
    values = {key: str(value) for key, value in DEFAULTS_INT.items()}
    values.update({key: str(value) for key, value in DEFAULTS_BOOL.items()})
    values["listen_to_quran"] = DEFAULT_CRON
    values["athkar_elsabah_mode"] = DEFAULT_ATHKAR_ELSABAH_MODE
    values["athkar_elsabah_clock"] = DEFAULT_ATHKAR_ELSABAH_CLOCK
    values["friday_quran_position"] = DEFAULT_FRIDAY_QURAN_POSITION
    values.update(read_default_settings(default_settings_file))
    for key in RETIRED_KEYS:
        values.pop(key, None)
    for key in KEPT_ON_RESET:
        if current.get(key, ""):
            values[key] = current[key]
    return values


def reset_audio(wanted, available):
    """The files the defaults name, among those this device has. A device with none of
    them gets every file ticked, so a reset never leaves an event with nothing to play."""
    chosen = audio_lists.checked_from_config(wanted) & set(available)
    return [name for name in available if name in chosen] if chosen else list(available)
