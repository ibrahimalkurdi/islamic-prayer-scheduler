"""Whether the device is on a network, the wifi networks around it, and joining one - all
through NetworkManager's nmcli, so the time app can offer a wifi picker on the touch screen
when the desktop's own wifi icon is hidden behind the fullscreen countdown.

No Qt here. Every function takes a runner (args, timeout) -> (returncode, output) so the
tests can stand in for nmcli; the default runs it for real.

Permission: NetworkManager lets a member of netdev scan and save networks without a
password only from the active desktop session (Raspberry Pi OS ships that polkit rule). A
countdown started from the desktop has it; one relaunched by the nightly updater from cron
does not, and connect() says so rather than failing silently.
"""

import subprocess
import threading
import time

NMCLI = "nmcli"
SCAN_TIMEOUT_SECONDS = 20
CONNECT_TIMEOUT_SECONDS = 45
STATUS_TIMEOUT_SECONDS = 5

CHECK_EVERY_SECONDS = 10
# The wifi watchdog (wifi_connectivity_resolver) brings a dropped interface back within
# about a minute by itself. The picker is for when it cannot: router off, password changed.
PROMPT_AFTER_SECONDS = 2 * 60
SNOOZE_SECONDS = 10 * 60

NETWORK_TYPES = ("wifi", "ethernet")


def run_nmcli(args, timeout):
    try:
        done = subprocess.run([NMCLI] + list(args), capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def split_terse(line):
    """One line of `nmcli -t` output into its fields. Colons inside a field (an SSID may
    have them) come escaped as \\: and a backslash as \\\\."""
    fields, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def network_connected(runner=run_nmcli):
    """True when a wifi or wired connection is up, False when none is, None when that
    cannot be said yet: nmcli cannot be asked (a machine without NetworkManager never
    shows the picker), or a connection is still being made, as it is just after boot."""
    code, output = runner(["-t", "-f", "TYPE,STATE", "device"], STATUS_TIMEOUT_SECONDS)
    if code != 0:
        return None
    connecting = False
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) < 2 or fields[0] not in NETWORK_TYPES:
            continue
        if fields[1] == "connected":
            return True
        if fields[1].startswith("connecting"):
            connecting = True
    return None if connecting else False


def scan(runner=run_nmcli):
    """Nearby networks, strongest first, one entry per name:
    [{"ssid", "signal", "secure", "in_use"}]. Hidden networks (no name) are left out."""
    runner(["radio", "wifi", "on"], STATUS_TIMEOUT_SECONDS)
    code, output = runner(["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi",
                           "list", "--rescan", "yes"], SCAN_TIMEOUT_SECONDS)
    if code != 0:
        return []
    best = {}
    for line in output.splitlines():
        fields = split_terse(line)
        if len(fields) < 4 or not fields[1]:
            continue
        in_use, ssid, signal, security = fields[0], fields[1], fields[2], fields[3]
        try:
            strength = int(signal)
        except ValueError:
            strength = 0
        entry = {"ssid": ssid, "signal": strength,
                 "secure": security.strip() not in ("", "--"), "in_use": in_use == "*"}
        if ssid not in best or strength > best[ssid]["signal"]:
            best[ssid] = entry
    return sorted(best.values(), key=lambda n: -n["signal"])


WRONG_PASSWORD = "كلمة المرور غير صحيحة. تأكد منها وحاول مرة أخرى."
NOT_ALLOWED = ("لا يمكن تغيير شبكة الواي فاي من هنا الآن. أعد تشغيل الجهاز ثم حاول مرة "
               "أخرى، أو استخدم أيقونة الواي فاي في أعلى سطح المكتب.")
NOT_FOUND = "لم يتم العثور على الشبكة. اقترب من الراوتر أو حدّث القائمة وحاول مرة أخرى."
FAILED = "تعذّر الاتصال بالشبكة. حاول مرة أخرى."


def connect(ssid, password="", runner=run_nmcli):
    """Join a network, saving it so the device rejoins it by itself. Returns
    (ok, message) - the message in the words the screen shows."""
    args = ["device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    code, output = runner(args, CONNECT_TIMEOUT_SECONDS)
    if code == 0:
        return True, ""
    text = output.lower()
    if "not authorized" in text or "insufficient privileges" in text:
        return False, NOT_ALLOWED
    if "secrets were required" in text or "psk" in text or "password" in text:
        return False, WRONG_PASSWORD
    if "no network with ssid" in text:
        return False, NOT_FOUND
    return False, FAILED


class WifiWatch:
    """When to open the picker: at once if the app starts with no network - someone is at
    the screen then - otherwise after PROMPT_AFTER_SECONDS without one, the watchdog having
    had its chance, and again SNOOZE_SECONDS after it was put off. Times are passed in, as
    in InternetWatch."""

    def __init__(self):
        self.down_since = None
        self.snoozed_until = None
        self.launching = True

    def record(self, connected, now):
        if connected is None:
            # Still connecting, or nmcli unavailable: not an answer. It neither starts nor
            # ends the wait - with the router off, NetworkManager retries all the time, and
            # restarting the count on each try would keep the picker away for good - and it
            # does not use up the at-launch check.
            return
        if connected is False:
            if self.down_since is None:
                self.down_since = now - PROMPT_AFTER_SECONDS if self.launching else now
        else:
            self.down_since = None
            self.snoozed_until = None
        self.launching = False

    def snooze(self, now):
        self.snoozed_until = now + SNOOZE_SECONDS

    def should_prompt(self, now):
        if self.down_since is None or now - self.down_since < PROMPT_AFTER_SECONDS:
            return False
        return self.snoozed_until is None or now >= self.snoozed_until

    def connected(self):
        return self.down_since is None


class WifiMonitor:
    """What the time app calls from its timer, the way InternetMonitor is: the nmcli
    check runs in the background, poll() never waits on it."""

    def __init__(self, runner=run_nmcli, clock=time.monotonic):
        self.runner = runner
        self.clock = clock
        self.watch = WifiWatch()
        self._result = None
        self._pending = False
        self._running = False
        self._next_check = 0

    def _check(self):
        try:
            self._result = network_connected(self.runner)
            self._pending = True
        finally:
            self._running = False

    def poll(self):
        """True while the picker should be on screen."""
        now = self.clock()
        if self._pending:
            self._pending = False
            self.watch.record(self._result, now)
        if not self._running and now >= self._next_check:
            self._running = True
            self._next_check = now + CHECK_EVERY_SECONDS
            threading.Thread(target=self._check, daemon=True).start()
        return self.watch.should_prompt(now)

    def snooze(self):
        self.watch.snooze(self.clock())
