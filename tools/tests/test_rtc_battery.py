"""The clock module's battery check, against a fake chip: fake i2cget/i2cset scripts, a
fake sysfs name file and a fake boot id. And the notice the time app opens.

    python3 tools/tests/test_rtc_battery.py
"""
import os, sys, stat, tempfile, subprocess

os.environ["QT_QPA_PLATFORM"] = "offscreen"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEVICE = os.path.join(REPO, "scheduler-official-touch-screen-with-raspberry-pi-4")
APPLICATIONS = os.path.join(DEVICE, "applications")
GUI_DIR = os.path.join(APPLICATIONS, "desktop/prayer_times_gui")
sys.path.insert(0, APPLICATIONS)
sys.path.insert(0, GUI_DIR)
from shared import rtc_battery as rtc

fails = []
def chk(name, got, want):
    ok = got == want
    print(("  ✓ " if ok else "  ✗ ") + name + ("" if ok else f"  expected {want!r}, got {got!r}"))
    if not ok: fails.append(name)


ROOT = tempfile.mkdtemp()
REGISTER = os.path.join(ROOT, "register")
WRITES = os.path.join(ROOT, "writes")


def script(name, body):
    path = os.path.join(ROOT, name)
    with open(path, "w") as f:
        f.write("#!/bin/bash\n" + body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


I2CGET = script("i2cget", f'[[ -f "{REGISTER}" ]] || exit 1\ncat "{REGISTER}"\n')
I2CSET = script("i2cset", f'echo "$*" >> "{WRITES}"\necho "${{@: -1}}" > "{REGISTER}"\n')


def write(path, text):
    with open(path, "w") as f:
        f.write(text)


def fresh(chip="ds3231", register="0x88", boot_id="boot-1"):
    for path in (REGISTER, WRITES, PENDING):
        if os.path.exists(path):
            os.remove(path)
    write(NAME, chip + "\n")
    if register is not None:
        write(REGISTER, register + "\n")
    write(BOOT, boot_id + "\n")


def boot(boot_id):
    write(BOOT, boot_id + "\n")


def writes():
    return open(WRITES).read().split("\n")[:-1] if os.path.exists(WRITES) else []


NAME = os.path.join(ROOT, "name")
BOOT = os.path.join(ROOT, "boot_id")
PENDING = os.path.join(ROOT, "state/rtc-battery-empty")
PATHS = dict(name_file=NAME, pending_file=PENDING, boot_id_file=BOOT,
             i2cget=I2CGET, i2cset=I2CSET)
state = lambda **extra: rtc.battery_state(**PATHS, **extra)

print("1. no clock module: nothing to say")
fresh(chip="")
chk("no name file content -> None", state(), None)
fresh(chip="pcf8563")
chk("a chip this check does not know -> None", state(), None)

print("2. a power cut with an empty battery")
fresh(register="0x88")
chk("flag set -> empty", state(), rtc.EMPTY)
chk("only the stop bit is cleared, the 32kHz bit kept", writes(), ["-f -y 1 0x68 0x0f 0x08"])
chk("the chip now reads clear", open(REGISTER).read().strip(), "0x08")
chk("the warning is written down with its boot", open(PENDING).read().strip(), "boot-1")

print("3. every start of the app warns again, the same boot included")
chk("the app started again", state(), rtc.EMPTY)
chk("and again", state(), rtc.EMPTY)
chk("cleared once, not on every start", len(writes()), 1)

print("4. a later boot with the clock still running: the battery works again")
boot("boot-2")
chk("ok", state(), rtc.OK)
chk("the warning is gone", os.path.exists(PENDING), False)
boot("boot-3")
chk("and stays gone", state(), rtc.OK)

print("5. a later boot, clock stopped again: still empty")
fresh(register="0x88")
state()
boot("boot-2")
write(REGISTER, "0x88\n")
chk("empty", state(), rtc.EMPTY)
chk("written down with the new boot", open(PENDING).read().strip(), "boot-2")
chk("the next start in that boot still warns", state(), rtc.EMPTY)

print("6. cleared by hand")
fresh(register="0x88")
state()
rtc.clear_pending(pending_file=PENDING)
chk("ok", state(), rtc.OK)

print("7. a healthy battery")
fresh(register="0x08")
chk("flag clear -> ok", state(), rtc.OK)
chk("nothing written to the chip", writes(), [])

print("8. --no-clear only reads")
fresh(register="0x88")
chk("empty", state(clear=False), rtc.EMPTY)
chk("chip untouched", writes(), [])
chk("nothing written down", os.path.exists(PENDING), False)

print("9. a warning that cannot be written down leaves the flag for next time")
fresh(register="0x88")
rtc.battery_state(**dict(PATHS, pending_file="/proc/no-such-dir/rtc-battery-empty"))
chk("flag not cleared", writes(), [])

print("10. a chip that cannot be read warns nobody")
fresh(register=None)
chk("unknown", state(), rtc.UNKNOWN)
fresh(register="garbage")
chk("unparseable output -> unknown", state(), rtc.UNKNOWN)
fresh(register="0x88")
state()
boot("boot-2")
os.remove(REGISTER)
chk("an unreadable chip does not clear a warning", state(), rtc.EMPTY)

print("11. the notice")
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from rtc_battery_dialog import RtcBatteryDialog
replaced = []
dialog = RtcBatteryDialog(on_replaced=lambda: replaced.append(True))
dialog.show()
chk("title", dialog.title.text(), rtc.TITLE)
chk("says to replace the battery", "تبديل بطارية" in dialog.message.text(), True)
dialog.ok_btn.click()
chk("OK does not end the warning", replaced, [])
chk("and hides it", dialog.isVisible(), False)
dialog.show()
dialog.replaced_btn.click()
chk("«battery replaced» ends it", replaced, [True])
chk("and hides it too", dialog.isVisible(), False)

print("12. the time app opens it and health_check reports it")
main_src = open(os.path.join(GUI_DIR, "main.py"), encoding="utf-8").read()
chk("time app checks as the countdown opens",
    "self.update_countdown()\n        # With the countdown" in main_src
    and "        self.check_rtc_battery()\n" in main_src, True)
chk("closing it is not remembered past this run",
    "rtc_battery.dismiss" not in main_src, True)
chk("«battery replaced» clears the warning",
    "on_replaced=rtc_battery.clear_pending" in main_src, True)
health = open(os.path.join(DEVICE, "config/scripts/health_check.sh")).read()
chk("health_check only reads", "python3 -m shared.rtc_battery --no-clear" in health, True)
chk("and never fails on it", 'empty) echo "  WARN' in health, True)
packages = open(os.path.join(DEVICE, "config/packages.txt")).read().split()
chk("i2c-tools is installed by the update", "i2c-tools" in packages, True)
cli = subprocess.run([sys.executable, "-m", "shared.rtc_battery", "--no-clear"],
                     cwd=APPLICATIONS, capture_output=True, text=True)
chk("command line runs", cli.returncode, 0)

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall passed")
