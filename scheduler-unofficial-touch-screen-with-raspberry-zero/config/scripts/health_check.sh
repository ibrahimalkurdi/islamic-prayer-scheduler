#!/bin/bash
# Is this device actually working?
#
#   health_check.sh            report every check, exit non-zero on the first failure
#   health_check.sh --quiet    same, but only print failures
#   health_check.sh --no-gui   skip the two checks that need the countdown on screen,
#                              for a Settings-driven update where it is deliberately down
#
# check_updates.sh runs this after an update and rolls back if it fails, so the checks
# have to mean something: "the process exists" is not the same as "the screen is right".
# A GUI that died on a traceback still leaves a process behind for a moment, and a
# scheduler with an unreadable prayer map runs all day playing nothing.
#
# Safe to run by hand at any time - it only reads.
set -u

MAIN_DIR="$HOME/Desktop/scheduler"
CONFIG_DIR="$MAIN_DIR/config"
APP_DIR="$MAIN_DIR/applications"
GUI_MAIN="$APP_DIR/desktop/prayer_times_gui/main.py"
SERVICE="audio_event_scheduler.service"

QUIET=0
NO_GUI=0
for arg in "$@"; do
    case "$arg" in
        --quiet)  QUIET=1 ;;
        --no-gui) NO_GUI=1 ;;
    esac
done

failures=0

pass() { [[ $QUIET -eq 1 ]] || echo "  OK    $1"; }
fail() { echo "  FAIL  $1" >&2; failures=$((failures + 1)); }

# 1. The athan service. Without this the device is silent, which is the whole point of it.
if systemctl is-active --quiet "$SERVICE"; then
    pass "$SERVICE is active"
else
    fail "$SERVICE is $(systemctl is-active "$SERVICE" 2>&1)"
fi

# 2. The countdown process. Skipped with --no-gui, which check_updates.sh passes for a
#    Settings-driven update: the countdown is deliberately not on screen there, and it is
#    verified separately by starting it offscreen, which is a stricter test than looking
#    at one that happens to be up.
GUI_PID=""
if [[ $NO_GUI -eq 1 ]]; then
    [[ $QUIET -eq 1 ]] || echo "  SKIP  GUI checks (--no-gui: countdown is checked offscreen instead)"
else
    GUI_PID="$(pgrep -f "prayer_times_gui/main.py" | head -1)"
    if [[ -n "$GUI_PID" ]]; then
        pass "prayer times GUI is running"
    else
        fail "prayer times GUI is not running"
    fi
fi

# 3. The countdown is drawing, not merely running. A window on screen is the only
#    evidence that separates a working app from one stuck on a traceback, and the app
#    is fullscreen, so its window is the size of the display.
#
#    The window has to be matched back to the countdown's own pid. Searching by class
#    alone matches any Python window - including the Settings app, which is running
#    whenever an update is driven from the touchscreen - so a class-only check passes
#    even when the countdown is closed, which is the opposite of useful.
if [[ $NO_GUI -eq 1 ]]; then
    :
elif [[ -z "$GUI_PID" ]]; then
    [[ $QUIET -eq 1 ]] || echo "  SKIP  window check (no GUI process to match a window to)"
elif command -v xdotool > /dev/null 2>&1; then
    GUI_WINDOW=""
    for wid in $(DISPLAY=:0 xdotool search --class "python" 2>/dev/null); do
        if [[ "$(DISPLAY=:0 xdotool getwindowpid "$wid" 2>/dev/null)" == "$GUI_PID" ]]; then
            GUI_WINDOW="$wid"
            break
        fi
    done
    if [[ -n "$GUI_WINDOW" ]]; then
        pass "GUI has a window on the display"
    else
        fail "no window on display :0 belongs to the GUI process"
    fi
else
    # Not installed on every image, and not worth pulling in as a dependency just for
    # this - the traceback check below covers the same failure from the other side.
    [[ $QUIET -eq 1 ]] || echo "  SKIP  window check (xdotool not installed)"
fi

# 4. Nothing crashed into the log since the process started. Catches the case where the
#    app relaunches in a loop, which leaves a live process at every instant.
GUI_LOG="$MAIN_DIR/logs/prayer_times_gui.log"
if [[ -f "$GUI_LOG" ]] && tail -n 40 "$GUI_LOG" | grep -q "Traceback (most recent call last)"; then
    fail "traceback in the last 40 lines of $(basename "$GUI_LOG")"
else
    pass "no recent traceback in the GUI log"
fi

# 5. The prayer map parses and covers today. A map that loads but has no row for today
#    means a silent day, and the countdown falls back to a grey --:-- screen.
map_error="$(python3 - "$CONFIG_DIR/prayer_times_map.py" 2>&1 <<'MAPCHECK'
import datetime, sys
try:
    namespace = {}
    with open(sys.argv[1], encoding="utf-8") as handle:
        exec(handle.read(), {}, namespace)
    rows = namespace["prayerTimes"]
    today = datetime.date.today()
    if not any(int(r["Month"]) == today.month and int(r["Day"]) == today.day for r in rows):
        raise SystemExit(f"no row for {today:%m-%d} among {len(rows)} rows")
except SystemExit:
    raise
except Exception as error:
    raise SystemExit(f"{type(error).__name__}: {error}")
MAPCHECK
)"
if [[ -z "$map_error" ]]; then
    pass "prayer map parses and covers today"
else
    fail "prayer map is unusable - $map_error"
fi

# 6. Settings parse. The GUIs read this on every start; a broken one takes both down.
if python3 -c "
import configparser, sys
c = configparser.ConfigParser()
c.read('$CONFIG_DIR/config.ini')
sys.exit(0 if c.has_section('Settings') else 1)
" 2>/dev/null; then
    pass "config.ini parses and has [Settings]"
else
    fail "config.ini is missing or has no [Settings] section"
fi

# 7. Every shipped Python file at least compiles. Cheap, and catches a half-written file
#    from an interrupted copy that none of the checks above would notice.
if find "$APP_DIR" -name '*.py' -print0 2>/dev/null | xargs -0 -r python3 -m py_compile 2>/dev/null; then
    pass "all application Python compiles"
else
    fail "a Python file under applications/ does not compile"
fi

if [[ $failures -eq 0 ]]; then
    [[ $QUIET -eq 1 ]] || echo "healthy"
    exit 0
fi
echo "unhealthy: $failures check(s) failed" >&2
exit 1
