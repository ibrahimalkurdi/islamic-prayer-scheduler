"""What version this device is actually running.

Moved here out of applications/desktop/prayer_times_gui/main.py so the website can print
the same number the touch screen prints, read from the same file by the same rule rather
than by a second copy of it that is free to drift.

The path is a parameter rather than a module constant, because the web server takes its
scheduler directory from --scheduler-dir and the tests point it at a fixture tree.
"""

import os

# What the label reads when there is no answer - a dash, not a blank, so the line keeps
# its height and an absent version looks deliberate instead of broken.
UNKNOWN = "—"


def version_file(scheduler_dir):
    return os.path.join(scheduler_dir, "var", "installed_version")


def installed_version(scheduler_dir):
    """Read on every call, never cached.

    check_updates.sh writes var/installed_version after a release passes its health
    check, so that file - not a constant baked into the payload - is the only honest
    answer. A constant would still read "1.0.0" on a device that has taken four updates.

    It also relaunches the apps *before* it runs that check, and writes the file only
    *after* it passes. A value read once at startup would therefore show the previous
    version for the whole life of the process - which is exactly the moment someone looks
    at this label to see whether an update landed.
    """
    try:
        with open(version_file(scheduler_dir), encoding="utf-8") as handle:
            version = handle.read().strip()
    except OSError:
        return UNKNOWN
    return version if version and version != "unknown" else UNKNOWN
