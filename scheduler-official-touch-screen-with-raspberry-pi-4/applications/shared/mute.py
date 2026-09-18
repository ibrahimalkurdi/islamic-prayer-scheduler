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


def audio_set_mute(muted):
    """Silence or restore the output device. False if the device could not be reached."""
    try:
        subprocess.run(AUDIO_MUTE_CMD + ["1" if muted else "0"], check=True,
                       capture_output=True, timeout=AUDIO_CMD_TIMEOUT)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def audio_is_muted():
    """Whether the output device is silenced, or None if it cannot be asked."""
    try:
        state = subprocess.run(AUDIO_STATE_CMD, check=True, capture_output=True,
                               text=True, timeout=AUDIO_CMD_TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return "[MUTED]" in state


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
