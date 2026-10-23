"""Silencing the athan, for however long the mute is set to last.

Moved here out of applications/desktop/prayer_times_gui/main.py so the website can offer
the same button the touch screen has. Nothing has to be told when the other one acts:
the flag file is the state, and the GUI's sync_mute_state already follows the file rather
than its own taps, so a mute set from a phone reaches the screen on its next poll.
"""

import os
import subprocess
from datetime import datetime, timedelta

# The scheduler service, this GUI and the web server all run as the same desktop user, so
# a plain file under var/ is all that is needed to pass the mute state between them - no
# restart, no sudo.
SCHEDULER_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "scheduler")
MUTE_FLAG_FILE = os.path.join(SCHEDULER_DIR, "var", "mute.flag")
PLAYER_SCRIPT_FILE = os.path.join(SCHEDULER_DIR, "config", "scripts", "play_audio.sh")
# Muting is temporary: the flag holds the epoch second the mute lapses, so the scheduler
# and the player can each honour the expiry on their own. Keeping the deadline in the
# file rather than in this process means a mute still lifts if the GUI is closed or
# restarted while it is active - otherwise the athan could stay off with no way back.
MUTE_DURATION_MINUTES = 60

# Muting acts on the output device, not on the player: an athan already playing goes
# silent at once and comes back mid-stream when unmuted. Killing the player silences it
# just as fast, but nothing can bring it back - so that is only the fallback, for a
# device where the device cannot be reached.
#
# wpctl ships with wireplumber, the session manager already running here. pactl is not
# installed on the device and amixer finds no usable Master control on this hardware.
#
# wpctl talks to the user's PipeWire socket, which it finds through XDG_RUNTIME_DIR. A
# desktop session sets that; a systemd service does not, so the web server's unit sets it
# explicitly. Without it every call here fails and the caller falls back to killing the
# player - which silences the athan but cannot be undone.
AUDIO_SINK = "@DEFAULT_AUDIO_SINK@"
AUDIO_MUTE_CMD = ["wpctl", "set-mute", AUDIO_SINK]
AUDIO_STATE_CMD = ["wpctl", "get-volume", AUDIO_SINK]
AUDIO_CMD_TIMEOUT = 3

def _runtime_dir():
    """Where wpctl should look for the PipeWire socket.

    A desktop session exports XDG_RUNTIME_DIR; a systemd service does not, and the unit's
    own Environment= line leans on systemd resolving %U to the User= uid. An inherited
    value is therefore not trusted on its own - a wrong one is worse than none, because
    it is set, and merely filling in a blank would leave it in place. This process's own
    uid is the answer whenever that directory is really there.
    """
    own = f"/run/user/{os.getuid()}"
    if os.path.isdir(own):
        return own
    inherited = os.environ.get("XDG_RUNTIME_DIR")
    if inherited and os.path.isdir(inherited):
        return inherited
    return own


os.environ["XDG_RUNTIME_DIR"] = _runtime_dir()


def _session_bus():
    """The session bus socket, for the same reason and with the same caution.

    PipeWire's rt module asks the session bus for realtime scheduling. With no address
    set, libdbus tries to autolaunch a daemon, which needs $DISPLAY - and a service has
    none, so wpctl exits 2 with "Unable to autolaunch a dbus-daemon without a $DISPLAY".
    Naming the socket that is already there avoids the autolaunch entirely.
    """
    own = os.path.join(os.environ["XDG_RUNTIME_DIR"], "bus")
    if os.path.exists(own):
        return f"unix:path={own}"
    return os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")


_bus = _session_bus()
if _bus:
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = _bus

# Why the last wpctl call failed, for the log and for the website - "the speaker could
# not be reached" on its own is not something anyone can act on.
_last_error = ""


def last_error():
    return _last_error


def _record(command, error=None, result=None):
    global _last_error
    if error is not None:
        _last_error = f"{' '.join(command)}: {error}"
    elif result is not None and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        _last_error = (f"{' '.join(command)}: exit {result.returncode}"
                       + (f" - {detail[0]}" if detail else ""))
    else:
        _last_error = ""
    return _last_error


def audio_set_mute(muted):
    """Silence or restore the output device. False if the device could not be reached."""
    command = AUDIO_MUTE_CMD + ["1" if muted else "0"]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=AUDIO_CMD_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        _record(command, error=error)
        return False
    _record(command, result=result)
    return result.returncode == 0


def audio_is_muted():
    """Whether the output device is silenced, or None if it cannot be asked."""
    try:
        result = subprocess.run(AUDIO_STATE_CMD, capture_output=True, text=True,
                                timeout=AUDIO_CMD_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        _record(AUDIO_STATE_CMD, error=error)
        return None
    if result.returncode != 0:
        _record(AUDIO_STATE_CMD, result=result)
        return None
    _record(AUDIO_STATE_CMD, result=result)
    return "[MUTED]" in result.stdout


def mute_expiry():
    """Epoch second this mute ends, or None if there is no readable mute in force."""
    try:
        with open(MUTE_FLAG_FILE) as flag:
            return int(flag.read().strip())
    except (OSError, ValueError):
        return None


def is_muted():
    expiry = mute_expiry()
    return expiry is not None and datetime.now().timestamp() < expiry


def write_mute_flag(minutes=MUTE_DURATION_MINUTES):
    """Start a mute, and return the instant it lapses."""
    deadline = datetime.now() + timedelta(minutes=minutes)
    os.makedirs(os.path.dirname(MUTE_FLAG_FILE), exist_ok=True)
    with open(MUTE_FLAG_FILE, "w") as flag:
        flag.write(f"{int(deadline.timestamp())}\n")
    return deadline


def clear_mute_flag():
    try:
        os.remove(MUTE_FLAG_FILE)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def stop_current_audio():
    """Muting part way through an athan should cut what is already playing. The
    player script kills its own vlc child from its EXIT trap, so signalling the
    script is enough - and it runs as this same user, so no sudo is involved."""
    try:
        subprocess.run(["pkill", "-TERM", "-f", PLAYER_SCRIPT_FILE], check=False)
    except OSError:
        pass


# The speaker's volume, set from the website's speaker button. Like the mute it is
# temporary by default: the flag holds when it lapses and the volume to go back to, and
# whoever sees it lapse puts that volume back - the web server, which is always running,
# checks every VOLUME_CHECK_SECONDS. Set as permanent, there is no flag and it stays.
VOLUME_FLAG_FILE = os.path.join(SCHEDULER_DIR, "var", "volume.flag")
VOLUME_DURATION_MINUTES = MUTE_DURATION_MINUTES
# What the volume panel's reset button sets, and keeps.
DEFAULT_VOLUME = 50
VOLUME_CHECK_SECONDS = 30
AUDIO_VOLUME_CMD = ["wpctl", "set-volume", AUDIO_SINK]


def audio_volume():
    """The output device's volume in percent, or None if it cannot be asked."""
    try:
        result = subprocess.run(AUDIO_STATE_CMD, capture_output=True, text=True,
                                timeout=AUDIO_CMD_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        _record(AUDIO_STATE_CMD, error=error)
        return None
    _record(AUDIO_STATE_CMD, result=result)
    words = result.stdout.split()
    if result.returncode != 0 or len(words) < 2 or words[0] != "Volume:":
        return None
    try:
        return round(float(words[1]) * 100)
    except ValueError:
        return None


def audio_set_volume(percent):
    """Set the output device's volume, 0-100. False if the device could not be reached."""
    level = max(0, min(100, int(percent)))
    command = AUDIO_VOLUME_CMD + [f"{level / 100:.2f}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=AUDIO_CMD_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        _record(command, error=error)
        return False
    _record(command, result=result)
    return result.returncode == 0


def temporary_volume():
    """{"until": epoch second, "restore": percent} while a temporary volume is set, else
    None - an unreadable flag included."""
    try:
        with open(VOLUME_FLAG_FILE) as flag:
            until, restore = (int(part) for part in flag.read().split())
    except (OSError, ValueError):
        return None
    return {"until": until, "restore": restore}


def set_volume(percent, permanent=False):
    """Set the volume, for VOLUME_DURATION_MINUTES unless permanent. A second temporary
    change keeps the volume the first one will go back to, and starts the hour again.
    Returns False, changing nothing kept, if the device could not be reached."""
    before = temporary_volume()
    restore = before["restore"] if before else audio_volume()
    if not audio_set_volume(percent):
        return False
    if permanent or restore is None:
        clear_volume_flag()
        return True
    until = int((datetime.now() + timedelta(minutes=VOLUME_DURATION_MINUTES)).timestamp())
    os.makedirs(os.path.dirname(VOLUME_FLAG_FILE), exist_ok=True)
    with open(VOLUME_FLAG_FILE, "w") as flag:
        flag.write(f"{until} {restore}\n")
    return True


def clear_volume_flag():
    try:
        os.remove(VOLUME_FLAG_FILE)
    except OSError:
        pass


def restore_lapsed_volume(now=None):
    """Put back the volume a lapsed temporary one replaced. True if it did."""
    held = temporary_volume()
    if held is None:
        if os.path.exists(VOLUME_FLAG_FILE):
            clear_volume_flag()
        return False
    if (now or datetime.now()).timestamp() < held["until"]:
        return False
    if not audio_set_volume(held["restore"]):
        return False
    clear_volume_flag()
    return True
