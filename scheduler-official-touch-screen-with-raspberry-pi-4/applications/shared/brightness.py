"""The touch screen's backlight, for the Settings app and the website.

The kernel exposes it as /sys/class/backlight/<name>/brightness. Raspberry Pi OS makes that
file writable by the video group, which the device user is in, so no root and no helper is
needed. The official 7" screen shows up as 10-0045. The name is looked up rather than fixed,
so Touch Display 2 and other DSI panels work too.

The panel comes back at full brightness on every boot. The value the user confirmed is kept
in var/brightness, which updates leave alone, and the website service writes it back when
it starts.

A change is shown first and kept only once confirmed. Anything that was only shown goes back
to the value from before it.
"""

import os
import time

BACKLIGHT_ROOT_ENV = "SCHEDULER_BACKLIGHT_ROOT"
DEFAULT_BACKLIGHT_ROOT = "/sys/class/backlight"
# Never dark enough to lose the screen that would turn it back up.
MIN_PERCENT = 10
MAX_PERCENT = 100
SAVED_FILE = os.path.join("var", "brightness")
# The backlight driver can come up after the website service at boot.
RESTORE_WAIT_SECONDS = 60


class BrightnessError(Exception):
    """Why the backlight could not be changed, in Arabic, for the person who tried."""


def backlight_root():
    return os.environ.get(BACKLIGHT_ROOT_ENV) or DEFAULT_BACKLIGHT_ROOT


def device():
    """The backlight's directory, or None on a device without a dimmable screen."""
    root = backlight_root()
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return None
    for name in names:
        path = os.path.join(root, name)
        if os.path.isfile(os.path.join(path, "brightness")) and \
                os.path.isfile(os.path.join(path, "max_brightness")):
            return path
    return None


def _read_int(path):
    with open(path, encoding="ascii") as handle:
        return int(handle.read().strip())


def clamp(percent):
    try:
        value = int(round(float(percent)))
    except (TypeError, ValueError):
        raise BrightnessError("قيمة السطوع غير صحيحة") from None
    return max(MIN_PERCENT, min(MAX_PERCENT, value))


def read():
    """The screen's brightness now, in percent, or None if there is no backlight."""
    path = device()
    if path is None:
        return None
    try:
        top = _read_int(os.path.join(path, "max_brightness"))
        raw = _read_int(os.path.join(path, "brightness"))
    except (OSError, ValueError):
        return None
    if top <= 0:
        return None
    return max(0, min(MAX_PERCENT, round(raw * 100 / top)))


def write(percent):
    """Sets the screen to `percent`, held within MIN..MAX. Returns the value used."""
    path = device()
    if path is None:
        raise BrightnessError("لا توجد شاشة يمكن ضبط سطوعها على هذا الجهاز")
    value = clamp(percent)
    try:
        top = _read_int(os.path.join(path, "max_brightness"))
        with open(os.path.join(path, "brightness"), "w", encoding="ascii") as handle:
            handle.write(str(max(1, round(top * value / 100))))
    except PermissionError:
        raise BrightnessError("لا يملك المستخدم صلاحية تغيير سطوع الشاشة "
                              "(يجب أن يكون ضمن مجموعة video)") from None
    except (OSError, ValueError) as error:
        raise BrightnessError(f"تعذّر تغيير سطوع الشاشة: {error}") from None
    return value


def saved(scheduler_dir):
    """The last confirmed brightness, or None if it was never changed here."""
    try:
        return clamp(open(os.path.join(scheduler_dir, SAVED_FILE), encoding="ascii").read())
    except (OSError, BrightnessError):
        return None


def save(scheduler_dir, percent):
    value = clamp(percent)
    path = os.path.join(scheduler_dir, SAVED_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="ascii") as handle:
        handle.write(f"{value}\n")
    os.replace(temporary, path)
    return value


def confirmed(scheduler_dir):
    """What a change that was only shown goes back to: the saved value, or the screen as
    it is now if nothing was ever saved."""
    value = saved(scheduler_dir)
    return value if value is not None else read()


def restore(scheduler_dir, wait_seconds=0):
    """Writes the saved value back, waiting up to `wait_seconds` for the backlight to
    appear. Returns the value written, or None when there was nothing to do."""
    value = saved(scheduler_dir)
    if value is None:
        return None
    deadline = time.monotonic() + wait_seconds
    while device() is None and time.monotonic() < deadline:
        time.sleep(1)
    if device() is None:
        return None
    return write(value)


def status(scheduler_dir):
    """For the settings page: None hides the section on a device with no backlight."""
    now = read()
    if now is None:
        return None
    return {"percent": now, "saved": confirmed(scheduler_dir),
            "min": MIN_PERCENT, "max": MAX_PERCENT}


def question(before, after):
    return f"هل تريد تغيير سطوع الشاشة من {before}% إلى {after}%؟"
