"""The time zone the device's clock shows, and moving it to another.

The operating system's own zone, which every clock on the device reads.
Changing it is root's, so it goes through the helper the device user may already run
without a password, and ends in a reboot - every program running read the old zone when
it started. The Settings app and the website both change it through here.

The zone also decides the daylight-saving shifts the prayer times get (prayer_dst.py),
so the schedule is rebuilt for the new zone first, while there is still time to.
"""

import configparser
import os
import subprocess

from shared import prayer_source

SYSTEM_APPLY = "/usr/local/sbin/scheduler-apply-system"
TIMEOUT_SECONDS = 30
APPLY_TIMEOUT_SECONDS = 300


class ZoneError(Exception):
    """A change that was refused or failed, with the message the owner is shown."""


def current():
    """The zone the clock shows now, e.g. "Europe/Berlin", or "" when it cannot be told."""
    try:
        zone = subprocess.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
        if zone:
            return zone
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        target = os.path.realpath("/etc/localtime")
    except OSError:
        return ""
    marker = "/zoneinfo/"
    return target.split(marker, 1)[1] if marker in target else ""


def known(zone, table):
    """Whether the zone is one the screens offer: the same country and city table as the
    daylight-saving choice."""
    return any(tz == zone for _country, _code, cities in table for _city, tz in cities)


def name(zone, table):
    """"الدولة — المدينة" for a zone in the table, the zone itself otherwise."""
    for country, _code, cities in table:
        for city, tz in cities:
            if tz == zone:
                return country if len(cities) == 1 else f"{country} — {city}"
    return zone


def country_of(zone, table):
    """The index of the country the zone belongs to, or None."""
    for index, (_country, _code, cities) in enumerate(table):
        if any(tz == zone for _city, tz in cities):
            return index
    return None


def prayer_offer(zone, table, scheduler_dir, recorded):
    """The city files to offer with a move to `zone`: those of its country, by name.
    None when the file in use is already one of that country's - nothing to change - and
    [] when the device has no city file for it."""
    zones = prayer_source.preset_zones(prayer_source.presets_dir(scheduler_dir))
    country = country_of(zone, table)
    offered = sorted(n for n, z in zones.items()
                     if country is not None and country_of(z, table) == country)
    current = os.path.basename(recorded or "")
    if current in offered:
        return None
    # The city whose zone is exactly the new one first: the likeliest choice.
    return sorted(offered, key=lambda n: zones[n] != zone)


def question(zone, table, offered=None, hand_edits=False):
    """The question before a change. With city files offered, the screen shows them in
    a list under this text, and no reminder is needed."""
    text = (f"سيتم تغيير المنطقة الزمنية لساعة الجهاز إلى «{name(zone, table)}»، "
            "ثم يُعاد تشغيل الجهاز تلقائيًا خلال ثوانٍ.\n")
    if offered:
        text += ("\nاختر ملف مواقيت الصلاة للمدينة الجديدة، ليُستخدم بدل الملف الحالي "
                 f"«{prayer_source.isolated(prayer_source.REFERENCE_NAME)}» على سطح المكتب:")
        if hand_edits:
            text = f"{text}\n\n{prayer_source.HAND_EDITS_WARNING}"
    else:
        text += "تذكّر أن تختار أيضًا ملف مواقيت الصلاة للمدينة الجديدة.\n\nهل تريد المتابعة؟"
    return text


def rebuild(scheduler_dir, zone=None, log_mode="w"):
    """apply_settings.sh, with TZ set to `zone` so prayer_dst reads the zone about to be
    the clock's rather than the one it still is. True when it succeeded."""
    script = os.path.join(scheduler_dir, "config", "scripts", "apply_settings.sh")
    log = os.path.join(scheduler_dir, "logs", "apply_settings.log")
    env = {**os.environ, "TZ": zone} if zone else dict(os.environ)
    try:
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, log_mode, encoding="utf-8") as out:
            return subprocess.run(["/bin/bash", script], stdout=out, stderr=subprocess.STDOUT,
                                  env=env, timeout=APPLY_TIMEOUT_SECONDS).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _install_preset(preset, scheduler_dir, desktop_dir):
    """Copy a city file into the Desktop file and record it, as choosing it would.
    Returns what undo() needs to put everything back."""
    ini = os.path.join(scheduler_dir, "config", "config.ini")
    reference = prayer_source.reference_file(desktop_dir)
    source = os.path.join(prayer_source.presets_dir(scheduler_dir), preset)
    with open(ini, encoding="utf-8") as handle:
        ini_before = handle.read()
    try:
        with open(reference, "rb") as handle:
            reference_before = handle.read()
    except OSError:
        reference_before = None
    try:
        new_hash = prayer_source.install(source, reference, scheduler_dir)
    except prayer_source.SourceError as error:
        _undo((ini, ini_before, reference, reference_before))
        raise ZoneError(str(error))
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(ini_before)
    prayer_source.record(config["Settings"], source, reference, new_hash)
    with open(ini, "w", encoding="utf-8") as handle:
        config.write(handle)
    return ini, ini_before, reference, reference_before


def _undo(saved):
    if not saved:
        return
    ini, ini_before, reference, reference_before = saved
    with open(ini, "w", encoding="utf-8") as handle:
        handle.write(ini_before)
    if reference_before is None:
        if os.path.exists(reference):
            os.remove(reference)
    else:
        with open(reference, "wb") as handle:
            handle.write(reference_before)


def change(zone, table, scheduler_dir, desktop_dir=None, preset=None):
    """Rebuild the schedule for the zone - with the city file `preset` copied in first,
    when one was chosen - set the zone and schedule the reboot. Raises ZoneError,
    leaving the zone, the prayer-times file and the schedule as they were."""
    if not known(zone, table):
        raise ZoneError("المنطقة الزمنية غير معروفة")
    if preset and preset not in (prayer_offer(zone, table, scheduler_dir, None) or []):
        raise ZoneError("ملف المواقيت المختار ليس من مدن هذه المنطقة")
    saved = _install_preset(preset, scheduler_dir, desktop_dir) if preset else None
    if not rebuild(scheduler_dir, zone):
        _undo(saved)
        rebuild(scheduler_dir, log_mode="a")
        raise ZoneError("تعذّر إعادة بناء جدول الأذان للمنطقة الجديدة، ولم تتغيّر المنطقة الزمنية.\n"
                        "راجع السجل logs/apply_settings.log على الجهاز.")
    try:
        result = subprocess.run(["sudo", "-n", SYSTEM_APPLY, "--timezone", zone],
                                capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as error:
        result = None
        reason = str(error)
    else:
        reason = (result.stderr or result.stdout).strip() or f"رمز الخروج {result.returncode}"
    if result is None or result.returncode != 0:
        # The schedule was just built for a zone the clock is not on.
        _undo(saved)
        rebuild(scheduler_dir, log_mode="a")
        raise ZoneError(f"تعذّر تغيير المنطقة الزمنية:\n{reason}")
