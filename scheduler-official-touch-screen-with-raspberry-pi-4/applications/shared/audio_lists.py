"""Which recitations sit in an event's folder, and which of them are ticked.

The Settings app draws this as a QListWidget of checkboxes and the website as a list of
<input type=checkbox>; both read the same folder and write the same comma-separated value
into config.ini, so a file ticked on the phone is ticked on the touch screen.
"""

import os

# One folder per event under the scheduler's audio/ directory. The folders themselves are
# created by apply_settings.sh on every run, so one a release adds appears the first time
# that release lands.
EVENT_DIRS = ("fajr", "shorooq", "duha", "athkar_elsabah", "dhuhr", "asr", "maghrib",
              "athkar_elmasa", "isha", "tahajjud", "quran", "friday_quran")

# Each event's on/off switch in config.ini, keyed by its list of ticked files. An event is
# only played with the files ticked for it, so one with none ticked is switched off when
# Settings are saved rather than left on and silent.
EVENT_ENABLE_KEYS = {
    "fajr_audio_checked": "enable_prayer_fajr",
    "sunrise_audio_checked": "enable_prayer_sunrise",
    "dhuhr_audio_checked": "enable_prayer_dhuhr",
    "asr_audio_checked": "enable_prayer_asr",
    "maghrib_audio_checked": "enable_prayer_maghrib",
    "isha_audio_checked": "enable_prayer_isha",
    "tahajjud_audio_checked": "enable_tahajjud_prayer",
    "duha_audio_checked": "enable_duha_prayer",
    "athkar_elsabah_audio_checked": "enable_athkar_elsabah",
    "athkar_elmasa_audio_checked": "enable_athkar_elmasa",
    "quran_audio_checked": "enable_listen_to_quran",
    "friday_quran_audio_checked": "enable_friday_quran",
}


def enables_without_audio(settings):
    """The enable keys to switch off: events that are on with no file ticked. `settings`
    is anything with .get(key, default) holding config.ini's string values."""
    return [enable for audio, enable in EVENT_ENABLE_KEYS.items()
            if str(settings.get(enable, "False")).strip().lower() == "true"
            and not checked_from_config(settings.get(audio, ""))]


def available_audio(directory):
    """The .mp3 files in one event folder, in the order the app lists them.

    An empty list for a folder that is not there: the Settings app draws its own
    "مجلد الملفات غير موجود" row in that case, and the website says the same thing, but
    neither should raise over a folder apply_settings.sh has not created yet."""
    if not os.path.isdir(directory):
        return []
    return sorted(f for f in os.listdir(directory) if f.lower().endswith(".mp3"))


def checked_from_config(value):
    """The comma-separated config.ini value as a set of file names."""
    return {f.strip() for f in (value or "").split(",") if f.strip()}


def checked_to_config(names):
    """Back to the config.ini form. Order is the caller's; the Settings app writes them
    in the order the list shows them, so the file stays readable."""
    return ",".join(names)


def audio_dir(scheduler_dir, event):
    return os.path.join(scheduler_dir, "audio", event)
