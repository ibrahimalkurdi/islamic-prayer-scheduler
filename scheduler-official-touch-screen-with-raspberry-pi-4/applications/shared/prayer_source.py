"""Which prayer-times file the device runs on, and choosing another.

The schedule is built from one file, the reference file on the Desktop. Choosing a source
copies a city preset (config/prayers-config/) or converts an Al Awail export (*-YYYY.csv
on the Desktop) into it. The Settings app and the website both choose through here, so
the two offer the same files and refuse the same ones in the same words.
"""

import configparser
import glob
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime

from shared.settings_rules import csv_is_valid_prayer_format, detect_csv_format

REFERENCE_NAME = "إدخال-مواقيت-الصلاة-للمستخدم.csv"
# Hash of the reference file as the app last wrote it, so a later choice can tell the
# owner edited it by hand since and ask before replacing those edits.
HASH_KEY = "prayer_csv_manual_hash"
# The file last copied in, for display and for «استعادة مواقيت المدينة». Never gates
# anything else: the reference file is the only thing the schedule reads.
SOURCE_LABEL_KEY = "prayer_csv_source_label"
# Beside the city files: the time zone each one's times are for.
ZONES_FILE = "zones.ini"

HAND_EDITS_WARNING = ("قد يحتوي ملف مواقيت الصلاة الحالي على تعديلات يدوية لم يقم بها التطبيق.\n"
                      "المتابعة الآن ستستبدل محتواه بالكامل بالملف الذي اخترته.")


class SourceError(Exception):
    """A choice that was refused, with the message the owner is shown."""


def reference_file(desktop_dir):
    return os.path.join(desktop_dir, REFERENCE_NAME)


def presets_dir(scheduler_dir):
    return os.path.join(scheduler_dir, "config", "prayers-config")


def isolated(name):
    """A file name kept whole inside Arabic text: without the isolate marks the bidi
    algorithm moves its «.csv» to the far end of the sentence."""
    return f"⁨{name}⁩"


def file_hash(path):
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def desktop_exports(desktop_dir):
    """Al Awail exports (*-YYYY.csv) copied to the Desktop. The reference file itself is
    not one: it is where every choice is copied to, so picking it would change nothing."""
    return sorted(glob.glob(os.path.join(desktop_dir, "*-[0-9][0-9][0-9][0-9].csv")))


def presets(prayers_config_dir):
    """Ready-to-use city files directly under prayers-config/ (not raw-imports/)."""
    if not os.path.isdir(prayers_config_dir):
        return []
    return [os.path.join(prayers_config_dir, name) for name in sorted(os.listdir(prayers_config_dir))
            if name.lower().endswith(".csv")
            and os.path.isfile(os.path.join(prayers_config_dir, name))]


def preset_zones(prayers_config_dir):
    """{file name: time zone} for the city files this device has that zones.ini names."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    try:
        parser.read(os.path.join(prayers_config_dir, ZONES_FILE), encoding="utf-8")
    except configparser.Error:
        return {}
    if not parser.has_section("zones"):
        return {}
    have = {os.path.basename(path) for path in presets(prayers_config_dir)}
    return {name: zone.strip() for name, zone in parser["zones"].items() if name in have}


def sources(prayers_config_dir, desktop_dir):
    """What there is to choose from: the city presets first, then any Al Awail exports."""
    return presets(prayers_config_dir) + desktop_exports(desktop_dir)


def current_source(recorded, prayers_config_dir):
    """The file the reference file was last copied from, as it exists on this device.
    A preset recorded under another device's home (settings copied from louay to ihms-lr)
    is the same preset here, found by its name. None when nothing can be restored from."""
    if not recorded:
        return None
    if os.path.isfile(recorded):
        return recorded
    if os.path.basename(os.path.dirname(recorded)) == os.path.basename(prayers_config_dir):
        here = os.path.join(prayers_config_dir, os.path.basename(recorded))
        if os.path.isfile(here):
            return here
    return None


def may_hold_hand_edits(section, reference):
    """Whether the reference file may hold edits this app did not make. A missing stored
    hash means there is no proof the app wrote the current file - a fresh upgrade, a first
    choice, a file typed by hand - so that counts as possibly edited too."""
    if not os.path.isfile(reference):
        return False
    stored = section.get(HASH_KEY, "").strip()
    current = file_hash(reference)
    return not stored or not current or stored != current


def install(source, reference, scheduler_dir):
    """Copy or convert source into the reference file. Returns the new file's hash.

    Raises SourceError with the message to show; on a refusal the reference file is
    either untouched or, for a conversion that produced a bad file, reported as such."""
    same_file = os.path.abspath(source) == os.path.abspath(reference)
    fmt = detect_csv_format(source)
    if fmt == "al_awail" and same_file:
        # The reference file itself in the raw format: refuse rather than read it while
        # truncating the same path.
        raise SourceError("ملف مواقيت الصلاة الحالي بصيغة غير محولة، الرجاء اختيار ملف آخر")
    try:
        os.makedirs(os.path.dirname(reference), exist_ok=True)
        if fmt == "al_awail":
            raw_imports = os.path.join(presets_dir(scheduler_dir), "raw-imports")
            os.makedirs(raw_imports, exist_ok=True)
            # Timestamped, so importing a name already archived keeps the earlier export.
            stem, ext = os.path.splitext(os.path.basename(source))
            shutil.copy2(source, os.path.join(
                raw_imports, f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{ext}"))
            convert = os.path.join(scheduler_dir, "config", "scripts", "00_al_awail_convert_csv.py")
            result = subprocess.run([sys.executable, convert, source, reference],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                raise SourceError(f"فشل تحويل ملف مواقيت الصلاة:\n{result.stderr or result.stdout}")
        elif fmt == "ready":
            if not same_file:
                shutil.copyfile(source, reference)
        else:
            raise SourceError("صيغة الملف المختار غير معروفة أو غير صالحة")
    except OSError as error:
        raise SourceError(f"فشل تطبيق ملف مواقيت الصلاة:\n{error}")

    if not csv_is_valid_prayer_format(reference):
        raise SourceError("الملف الناتج لا يطابق الصيغة المطلوبة:\n\n"
                          "Month,Day,Fajr,Sunrise,Dhuhr,Asr,Maghrib,Isha")
    return file_hash(reference)


def record(section, source, reference, new_hash):
    """What a successful choice leaves in config.ini. Re-choosing the reference file
    itself confirms it rather than naming a new source, so the record is kept."""
    if new_hash:
        section[HASH_KEY] = new_hash
    if os.path.abspath(source) != os.path.abspath(reference):
        section[SOURCE_LABEL_KEY] = source
