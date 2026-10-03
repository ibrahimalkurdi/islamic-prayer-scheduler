"""Whether the device can reach the internet, and what to tell the person at the screen.

The Pi 4 has no battery-backed clock. It takes the time from the internet, so a device
that loses power while offline comes back with the wrong time - and every athan with it.
Short of that, its clock drifts unchecked. Both screens say so while the internet is down.

The time app and the Settings app each run an InternetMonitor and show what it says, so
the two never disagree about when to warn. None of this holds Qt, and reachable() is the
only thing that touches the network - InternetMonitor runs it off the UI thread.
"""

import configparser
import os
import socket
import threading
import time

# Addresses, not names: a device whose DNS is broken has no internet either, and a name
# lookup that hangs would hold the check up far longer than the connect timeout.
PROBES = (("1.1.1.1", 443), ("8.8.8.8", 53), ("9.9.9.9", 443))
PROBE_TIMEOUT_SECONDS = 3
CHECK_EVERY_SECONDS = 30

# A router restart or a wifi blip is not worth a warning that flashes on and off.
WARN_AFTER_SECONDS = 5 * 60
BACK_SHOWN_SECONDS = 10
# Right after a reboot the wifi is still joining; an app started then has not found an
# outage, it is waiting for the network. It waits WARN_AFTER_SECONDS like any drop.
BOOT_GRACE_SECONDS = 5 * 60

ENABLE_KEY = "enable_internet_warning"
DEFAULT_ENABLED = True

OFFLINE_MESSAGE = ("لا يوجد اتصال بالإنترنت، وقد تصبح مواقيت الصلاة غير دقيقة. "
                   "يرجى توصيل الجهاز بالإنترنت.")
# For the daily list's narrow corner beside the date.
SHORT_OFFLINE_MESSAGE = "لا يوجد اتصال بالإنترنت، وقد تصبح المواقيت غير دقيقة."
BACK_MESSAGE = "عاد الاتصال بالإنترنت."

OFFLINE_BG = "#B45309"
BACK_BG = "#15803D"
TEXT_COLOR = "#FFFFFF"

STATE_OK = "ok"
STATE_OFFLINE = "offline"
STATE_BACK = "back"


def reachable(probes=PROBES, timeout=PROBE_TIMEOUT_SECONDS):
    """True when any probe accepts a connection. Blocks for up to timeout per probe."""
    for host, port in probes:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def seconds_since_boot():
    try:
        with open("/proc/uptime", encoding="ascii") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return float("inf")


def warning_enabled(ini_path):
    """The owner's choice in config.ini, on unless they turned it off."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(ini_path, encoding="utf-8")
        return parser.getboolean("Settings", ENABLE_KEY, fallback=DEFAULT_ENABLED)
    except (configparser.Error, ValueError):
        return DEFAULT_ENABLED


class InternetWatch:
    """Turns a series of reachable/unreachable results into what the screen shows.

    An app that starts offline warns at once: whoever just opened it is at the screen, and
    the outage did not start with the app - unless the device has just booted. A drop while
    it runs, or one met in the first BOOT_GRACE_SECONDS after boot, waits WARN_AFTER_SECONDS.
    Closing the warning lasts for this run of the app only, so opening it again while still
    offline warns again.

    Times are plain seconds (time.monotonic() in the apps), passed in so the rules can be
    tested without waiting five minutes."""

    def __init__(self):
        self.offline_since = None
        self.warned = False
        self.dismissed = False
        self.back_until = None
        self.launching = True

    def dismiss(self):
        """The person at the screen closed the warning: it stays closed for the rest of
        this outage. The next one warns again."""
        if self.warned:
            self.dismissed = True

    def record(self, online, now):
        if online:
            if self.warned:
                self.back_until = now + BACK_SHOWN_SECONDS
            self.offline_since = None
            self.warned = False
            self.dismissed = False
        else:
            if self.offline_since is None:
                self.offline_since = now - WARN_AFTER_SECONDS if self.launching else now
            self.back_until = None
            if now - self.offline_since >= WARN_AFTER_SECONDS:
                self.warned = True
        self.launching = False

    def state(self, now):
        if self.warned:
            return STATE_OK if self.dismissed else STATE_OFFLINE
        if self.back_until is not None and now < self.back_until:
            return STATE_BACK
        return STATE_OK

    def message(self, now):
        """(text, background) to show, or None when there is nothing to say."""
        state = self.state(now)
        if state == STATE_OFFLINE:
            return OFFLINE_MESSAGE, OFFLINE_BG
        if state == STATE_BACK:
            return BACK_MESSAGE, BACK_BG
        return None


class InternetMonitor:
    """What an app calls from its timer. poll() starts a check in the background when one
    is due and returns the message to show now, or None - never waiting on the network,
    so the screen keeps ticking while a check is out."""

    def __init__(self, ini_path, probe=reachable, clock=time.monotonic,
                 uptime=seconds_since_boot):
        self.ini_path = ini_path
        self.probe = probe
        self.clock = clock
        self.watch = InternetWatch()
        self.watch.launching = uptime() >= BOOT_GRACE_SECONDS
        self._result = None
        self._running = False
        self._next_check = 0
        self._enabled = DEFAULT_ENABLED
        self._ini_mtime = None

    def _check(self):
        try:
            self._result = bool(self.probe())
        finally:
            self._running = False

    def enabled(self):
        """Read again only when config.ini changes, since poll() runs every second."""
        try:
            mtime = os.stat(self.ini_path).st_mtime
        except OSError:
            mtime = None
        if mtime != self._ini_mtime:
            self._ini_mtime = mtime
            self._enabled = warning_enabled(self.ini_path)
        return self._enabled

    def dismiss(self):
        self.watch.dismiss()

    def poll(self):
        now = self.clock()
        if self._result is not None:
            online, self._result = self._result, None
            self.watch.record(online, now)
        if not self._running and now >= self._next_check:
            self._running = True
            self._next_check = now + CHECK_EVERY_SECONDS
            threading.Thread(target=self._check, daemon=True).start()
        if not self.enabled():
            return None
        return self.watch.message(now)
