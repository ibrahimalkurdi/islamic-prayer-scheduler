"""How large this device's screen draws the apps.

Both apps are laid out for the official 800x480 panel. A larger panel - the Zero's
1024x600 - would show the same pixels with a margin of unused space, and the fixed-size
buttons, clock and panels small against it. So such a device ships config/display.ini:

    [screen]
    scale = 1.25

and Qt draws everything that much larger, exactly as on the 800x480 panel. Applied
before QApplication is made, through QT_SCALE_FACTOR, which a process started from the
app - Settings from ⚙ - inherits. A scale already in the environment is left alone.
"""

import configparser
import os

SCALE_MIN = 1.0
SCALE_MAX = 3.0


def display_file(scheduler_dir):
    return os.path.join(scheduler_dir, "config", "display.ini")


def screen_scale(path):
    """The scale display.ini asks for, or None for none, or one outside sense."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
        scale = parser.getfloat("screen", "scale", fallback=None)
    except (configparser.Error, ValueError):
        return None
    if scale is None or not SCALE_MIN <= scale <= SCALE_MAX or scale == SCALE_MIN:
        return None
    return scale


def apply_screen_scale(scheduler_dir, environ=os.environ):
    if environ.get("QT_SCALE_FACTOR"):
        return
    scale = screen_scale(display_file(scheduler_dir))
    if scale is not None:
        environ["QT_SCALE_FACTOR"] = f"{scale:g}"
