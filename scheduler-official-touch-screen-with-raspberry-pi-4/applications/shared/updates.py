"""Software updates, as the Settings app and the website both offer them.

check_updates.sh does the work; this reads what it reports, edits config/update.conf, and
holds the questions both screens ask before an update changes what the device follows.
"""

import json
import os
import re
import subprocess

from shared.settings_rules import version_key

LIST_TIMEOUT_SECONDS = 30
STATUS_TIMEOUT_SECONDS = 20
VERSION_PATTERN = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")


def script(scheduler_dir):
    return os.path.join(scheduler_dir, "config", "scripts", "check_updates.sh")


def conf_file(scheduler_dir):
    return os.path.join(scheduler_dir, "config", "update.conf")


def _run(scheduler_dir, flag, timeout):
    try:
        return subprocess.run(["/bin/bash", script(scheduler_dir), flag], capture_output=True,
                              text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def status(scheduler_dir):
    """check_updates.sh --status, or {} when it cannot say."""
    try:
        return json.loads(_run(scheduler_dir, "--status", STATUS_TIMEOUT_SECONDS))
    except ValueError:
        return {}


def published(scheduler_dir):
    """Every published version for this device, newest first; [] without a network."""
    versions = [v.strip() for v in _run(scheduler_dir, "--list", LIST_TIMEOUT_SECONDS).splitlines()
                if v.strip()]
    return sorted(versions, key=version_key, reverse=True)


def latest(scheduler_dir):
    """The version the daily check would install - VERSIONS.json's, not the newest
    published. Empty when the pointer cannot be reached."""
    return _run(scheduler_dir, "--latest", LIST_TIMEOUT_SECONDS).strip()


def check_time(crontab_template):
    """(hour, minute) of the daily update check, or None.

    Read from the live crontab, because that is what actually runs; config/crontab.txt,
    which init.sh installs it from, only when the live one cannot be read."""
    try:
        text = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                              timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        text = ""
    if "check_updates.sh" not in text:
        try:
            with open(crontab_template, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            return None
    for line in text.splitlines():
        fields = line.split()
        if (len(fields) > 5 and not line.lstrip().startswith("#")
                and "check_updates.sh" in line
                and fields[0].isdigit() and fields[1].isdigit()):
            return int(fields[1]), int(fields[0])
    return None


def write_conf(path, key, value):
    """update.conf is plain shell, and the updater sources it - so a value is rewritten in
    place rather than the file regenerated, which would lose anything set by hand.
    Raises OSError."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        text = ""
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    text = pattern.sub(line, text) if pattern.search(text) else (text.rstrip("\n") + f"\n{line}\n")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def rollback_choices(installed, backup, versions):
    """(the retained backup or "", older published versions newest first). After a
    rollback the backup holds the version now running, and there is no going back to
    where you already are."""
    if backup == installed:
        backup = ""
    older = [v for v in versions
             if v != backup and (not installed or version_key(v) < version_key(installed))]
    return backup, sorted(older, key=version_key, reverse=True)


def hold_question(version):
    """Asked before installing anything but the approved version while the daily check
    is on: that night's check would undo it, so taking it turns the check off."""
    return (f"الإصدار {version} ليس أحدث إصدار معتمد.\n"
            "إن ثبّته فسيتوقف التحديث التلقائي اليومي، ويبقى الجهاز ثابتًا على الإصدار"
            f" {version}.\n\nهل تريد المتابعة؟")


def enable_question(installed, latest_version):
    """Asked before turning the daily check on when it would move the device at once, or
    "" when it would not."""
    if not latest_version or latest_version == installed:
        return ""
    if version_key(installed) > version_key(latest_version):
        text = (f"الإصدار المثبَّت {installed} أحدث من الإصدار المعتمد.\n"
                "إن فعّلت التحديث التلقائي اليومي فسيُرجَع الجهاز الآن إلى"
                f" الإصدار المعتمد: {latest_version}.")
    else:
        text = (f"الإصدار المثبَّت {installed} ليس أحدث إصدار معتمد.\n"
                "إن فعّلت التحديث التلقائي اليومي فسيُنقل الجهاز الآن إلى أحدث"
                f" إصدار: {latest_version}.")
    return text + "\n\nهل تريد المتابعة؟"
