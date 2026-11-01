"""Whether the clock module's coin cell kept the time through the last power cut.

Only devices fitted with a DS3231 clock module (README, "Add Real-Time Clock") have one;
on the rest there is nothing to check and nothing is shown.

The chip cannot measure its battery. What it has is the oscillator-stop flag: set when the
clock lost power and stopped, and never cleared by Linux's driver. When it is found set,
the warning is written down, with the boot it was found on, and the flag cleared so the
next power cut tests the battery afresh. The time app opens the warning at every start
until the battery is shown to work again; closing it only closes it for that run.

Shown to work means a later boot with the flag still clear. A Pi 4 restart cuts the
module's main power as a power cut does - on louay every restart with a flat cell stopped
the clock - so any later boot tests the cell. A warning can also be cleared by hand:

    python3 -m shared.rtc_battery --replaced

Read and cleared through i2c-tools as the device user, who is in the i2c group on
Raspberry Pi OS. When the chip cannot be read the answer is unknown, and unknown warns
nobody.
"""

import os
import subprocess
import sys

RTC_NAME_FILE = "/sys/class/rtc/rtc0/device/name"
SUPPORTED_CHIPS = ("ds3231",)
I2C_BUS = "1"
I2C_ADDRESS = "0x68"
STATUS_REGISTER = "0x0f"
OSCILLATOR_STOPPED = 0x80
I2CGET = "/usr/sbin/i2cget"
I2CSET = "/usr/sbin/i2cset"
I2C_TIMEOUT_SECONDS = 5
# Outside the release tree, so an update does not take the warning away.
PENDING_FILE = os.path.expanduser("~/.local/state/scheduler/rtc-battery-empty")
BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"

EMPTY = "empty"
OK = "ok"
UNKNOWN = "unknown"

TITLE = "بطارية الساعة فارغة"
MESSAGE = ("يرجى تبديل بطارية الساعة في الجهاز. بدونها قد تصبح مواقيت الأذان غير دقيقة "
           "بعد انقطاع الكهرباء.")
OK_BUTTON = "حسنًا"
# Taking the cell out with the power off stops the clock exactly as a flat cell does, and
# the chip cannot tell the two apart. Whoever just changed it can.
REPLACED_BUTTON = "تم تبديل البطارية"


def _read_text(path):
    try:
        with open(path, encoding="ascii") as handle:
            return handle.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def fitted(name_file=RTC_NAME_FILE):
    """True when a clock module this check understands is attached."""
    return _read_text(name_file) in SUPPORTED_CHIPS


def _i2c(command):
    try:
        done = subprocess.run(command, capture_output=True, text=True,
                              timeout=I2C_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def read_status(i2cget=I2CGET):
    """The status register as an int, or None when it cannot be read. -f because the
    kernel's RTC driver holds the address."""
    out = _i2c([i2cget, "-f", "-y", I2C_BUS, I2C_ADDRESS, STATUS_REGISTER])
    try:
        return int(out, 16) if out else None
    except ValueError:
        return None


def clear_stopped_flag(status, i2cset=I2CSET):
    """Clears only the oscillator-stop bit; the register's other bits are settings."""
    value = f"0x{status & ~OSCILLATOR_STOPPED & 0xFF:02x}"
    return _i2c([i2cset, "-f", "-y", I2C_BUS, I2C_ADDRESS, STATUS_REGISTER, value]) is not None


def pending(pending_file=PENDING_FILE):
    return os.path.exists(pending_file)


def _pending_boot(pending_file):
    return _read_text(pending_file)


def _mark_pending(boot_id, pending_file):
    try:
        os.makedirs(os.path.dirname(pending_file), exist_ok=True)
        with open(pending_file, "w", encoding="ascii") as handle:
            handle.write(boot_id + "\n")
        return True
    except OSError:
        return False


def clear_pending(pending_file=PENDING_FILE):
    try:
        os.remove(pending_file)
    except OSError:
        pass


def battery_state(clear=True, name_file=RTC_NAME_FILE, pending_file=PENDING_FILE,
                  boot_id_file=BOOT_ID_FILE,
                  i2cget=I2CGET, i2cset=I2CSET):
    """EMPTY, OK or UNKNOWN; None when no clock module is fitted.

    With clear=False nothing is written, to the chip or to the disk - for health_check.sh,
    which only reads."""
    if not fitted(name_file):
        return None
    boot_id = _read_text(boot_id_file)
    status = read_status(i2cget)
    if status is not None and status & OSCILLATOR_STOPPED:
        if clear and _mark_pending(boot_id, pending_file):
            clear_stopped_flag(status, i2cset)
        return EMPTY
    if pending(pending_file):
        survived = status is not None and _pending_boot(pending_file) != boot_id
        if not survived:
            return EMPTY
        if clear:
            clear_pending(pending_file)
    return UNKNOWN if status is None else OK


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--replaced" in arguments:
        clear_pending()
    state = battery_state(clear="--no-clear" not in arguments)
    print(state or "none")
