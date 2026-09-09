#!/bin/bash
# Pull a published release down and install it, or put the previous one back.
#
#   check_updates.sh                 cron: honours ENABLED, skips while audio is playing
#   check_updates.sh --now           update to the resolved target now
#   check_updates.sh --target 1.0.3  install one specific version, up or down
#   check_updates.sh --rollback      restore the retained previous version
#   check_updates.sh --list          print every published version for this variant
#
# Which version a device installs comes from VERSIONS.json in the repo, not from the
# release list - publishing a release does not roll it out. A PIN in config/update.conf
# overrides that file for one device.
#   check_updates.sh --status        print JSON for the Settings app
#
# The device tree holds the user's settings, their prayer times and hundreds of megabytes
# of their audio, interleaved with the code in the same directories - so this never
# replaces the tree wholesale. It replaces the paths the release names, minus the paths
# the release excludes, minus the paths this device excludes, minus a deny-list below
# that no release can override.
set -uo pipefail

MAIN_DIR="$HOME/Desktop/scheduler"
CONFIG_DIR="$MAIN_DIR/config"
SCRIPTS_DIR="$CONFIG_DIR/scripts"
VAR_DIR="$MAIN_DIR/var"
UPDATE_DIR="$VAR_DIR/update"
STAGING_DIR="$UPDATE_DIR/staging"
ROLLBACK_DIR="$UPDATE_DIR/rollback"
STATE_FILE="$UPDATE_DIR/state.json"
POINTER_FILE="$UPDATE_DIR/pointer.json"
INSTALLED_VERSION_FILE="$VAR_DIR/installed_version"
UPDATE_CONF="$CONFIG_DIR/update.conf"
LOG_FILE="$MAIN_DIR/logs/check_updates.log"
LOCK_FILE="$VAR_DIR/player.lock"
GUI_MAIN="$MAIN_DIR/applications/desktop/prayer_times_gui/main.py"
GUI_LOG="$MAIN_DIR/logs/prayer_times_gui.log"
# Kept apart from GUI_LOG so the offscreen check's output cannot be mistaken for the real
# app's, and so health_check.sh's traceback check does not read this run's noise.
GUI_VERIFY_LOG="$MAIN_DIR/logs/prayer_times_gui_check.log"
SERVICE="audio_event_scheduler.service"

# Overridable from update.conf so the whole flow can be pointed at a local directory for
# testing - curl reads file:// URLs, so no server is needed to exercise this end to end.
UPDATE_API_URL="${UPDATE_API_URL:-https://api.github.com/repos/ibrahimalkurdi/islamic-prayer-scheduler/releases}"
UPDATE_DOWNLOAD_URL="${UPDATE_DOWNLOAD_URL:-https://github.com/ibrahimalkurdi/islamic-prayer-scheduler/releases/download}"

# The one file that decides what every device runs. Publishing a release does not roll
# it out - this file does, and moving a value back one version rolls that fleet back on
# the next check. Devices never pick a version for themselves.
UPDATE_POINTER_URL="${UPDATE_POINTER_URL:-https://raw.githubusercontent.com/ibrahimalkurdi/islamic-prayer-scheduler/main/VERSIONS.json}"

# This updater's own version. A release may demand a newer one via min_updater, in which
# case the device stays where it is rather than applying something it cannot apply safely.
UPDATER_VERSION="1.0.0"

# How long to let the apps settle before judging them, and where to read the board's
# identity. Both overridable so the whole flow can be exercised off-device.
HEALTH_SETTLE_SECONDS="${HEALTH_SETTLE_SECONDS:-15}"
# How long the offscreen countdown must stay up to count as started. Long enough to get
# past widget construction and the first paint, short enough not to stall the dialog.
GUI_VERIFY_SECONDS="${GUI_VERIFY_SECONDS:-8}"
DEVICE_MODEL_FILE="${DEVICE_MODEL_FILE:-/proc/device-tree/model}"

# Never replaced, whatever a release asks for. The manifest proposes; this disposes.
# Without it a malformed or tampered release could name config.ini and a device would
# obey. These are rsync patterns, applied to the transfer root.
DENY_LIST=(
    "audio/" "var/" "logs/"
    "config/config.ini" "config/update.conf"
    "config/*.csv" "config/executed-events.json"
    "**/prayer_times_map.py" "**/__pycache__/"
    "*.pyc"
)

# Kept before the loop below consumes them: the re-exec further down has to hand the
# same arguments to the copy, and by then $@ is empty.
ORIGINAL_ARGS=("$@")

# MODE is two things at once, and both matter:
#   cron  - unattended. Obeys ENABLED, and the countdown is what the screen is for, so it
#           goes back up and gets checked on the display.
#   now   - somebody is looking at the fullscreen Settings app. Putting the countdown back
#           would map it over that window, so it stays down and is checked offscreen.
# Bare invocation stays "cron" because that is what the shipped crontab line calls, and
# devices in the field carry that line. --cron says the same thing out loud; --now is
# what the Settings app runs, and what to use when testing that path by hand.
MODE="cron"
TARGET_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cron)     MODE="cron" ;;
        --now)      MODE="now" ;;
        --rollback) MODE="rollback" ;;
        --status)   MODE="status" ;;
        --list)     MODE="list" ;;
        --target)   MODE="now"; TARGET_ARG="${2:-}"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

mkdir -p "$UPDATE_DIR" "$ROLLBACK_DIR" "$(dirname "$LOG_FILE")"

log() {
    local line="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$line"
    [[ "$MODE" == "status" || "$MODE" == "list" ]] || echo "$line" >> "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# Run from a copy of ourselves
# ---------------------------------------------------------------------------
# This script is inside the payload it installs, and bash reads a script incrementally
# as it executes - replacing it mid-run would carry on reading the new file at the old
# byte offset. Re-exec from a copy before touching anything.
if [[ "${SCHEDULER_UPDATER_DETACHED:-0}" != "1" \
      && "$MODE" != "status" && "$MODE" != "list" ]]; then
    SELF_COPY="$(mktemp -t check_updates.XXXXXX.sh)"
    cp "${BASH_SOURCE[0]}" "$SELF_COPY"
    chmod +x "$SELF_COPY"
    export SCHEDULER_UPDATER_DETACHED=1
    trap 'rm -f "$SELF_COPY"' EXIT
    bash "$SELF_COPY" "${ORIGINAL_ARGS[@]+"${ORIGINAL_ARGS[@]}"}"
    exit $?
fi

# ---------------------------------------------------------------------------
# Device configuration
# ---------------------------------------------------------------------------
VARIANT=""
ENABLED="true"
PIN=""
APPLY_MODE=""
EXTRA_EXCLUDE=""
# shellcheck disable=SC1090
[[ -f "$UPDATE_CONF" ]] && source "$UPDATE_CONF"

INSTALLED="$(cat "$INSTALLED_VERSION_FILE" 2>/dev/null || echo "unknown")"

detect_variant() {
    # The hardware has the final say: a card cloned from the other device carries the
    # wrong VARIANT in update.conf, and installing the wrong build would be destructive.
    local model
    model="$(cat "$DEVICE_MODEL_FILE" 2>/dev/null | tr -d '\0')"
    case "$model" in
        *"Raspberry Pi 4"*|*"Raspberry Pi 5"*|*"Compute Module 4"*) echo "pi4" ;;
        *"Raspberry Pi Zero"*)                                      echo "zero" ;;
        *) echo "" ;;
    esac
}

write_state() {
    # $1 result, $2 message, $3 needs_attention - "keep" leaves the existing one alone,
    # so a run that installs nothing cannot quietly discard a warning still outstanding.
    python3 - "$STATE_FILE" "$INSTALLED" "${1:-}" "${2:-}" "${3:-}" <<'STATE'
import json, sys, datetime
path, installed, result, message, attention = sys.argv[1:6]
if attention == "keep":
    try:
        attention = json.load(open(path)).get("needs_attention", "")
    except Exception:
        attention = ""
json.dump({
    "installed": installed,
    "result": result,
    "message": message,
    "needs_attention": attention,
    "at": datetime.datetime.now().isoformat(timespec="seconds"),
}, open(path, "w"), indent=2)
STATE
}

json_field() { python3 -c "
import json,sys
try: print(json.load(open(sys.argv[1])).get(sys.argv[2], '') or '')
except Exception: print('')
" "$1" "$2" 2>/dev/null; }

json_list() { python3 -c "
import json,sys
try:
    v = json.load(open(sys.argv[1])).get(sys.argv[2]) or []
    print('\n'.join(str(x) for x in v))
except Exception: pass
" "$1" "$2" 2>/dev/null; }

# Every published version for this variant, oldest first. Tags are variant-prefixed
# because releases/latest resolves to the newest release in the repo regardless of
# variant - without the prefix, a release for one variant would strand the other.
published_versions() {
    curl -fsSL "$UPDATE_API_URL" 2>/dev/null | python3 -c "
import json, sys, re
prefix = '${VARIANT}-v'
try:
    releases = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if isinstance(releases, dict):
    releases = releases.get('releases', [])
tags = [r['tag_name'][len(prefix):] for r in releases
        if isinstance(r, dict) and str(r.get('tag_name', '')).startswith(prefix)
        and not r.get('draft') and not r.get('prerelease')]
def key(v):
    return [int(p) if p.isdigit() else 0 for p in re.split(r'[._-]', v)]
print('\n'.join(sorted(set(tags), key=key)))
" 2>/dev/null
}

# The pointer is fetched once and kept, because two things are read out of it at very
# different moments - the target version before anything is downloaded, and this
# variant's path rules after the archive is unpacked. Two fetches could disagree.
fetch_pointer() {
    local body
    rm -f "$POINTER_FILE"
    body="$(curl -fsSL "$UPDATE_POINTER_URL" 2>/dev/null)" || return 1
    printf '%s' "$body" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null || return 2
    printf '%s' "$body" > "$POINTER_FILE"
}

# Empty output means the pointer names no version for this variant, which is a real
# answer - "install nothing" - and not the same as having failed to read the file.
# Accepts both forms: "pi4": "1.2.0" and "pi4": {"version": "1.2.0", ...}.
pointer_version() {
    python3 - "$POINTER_FILE" "$VARIANT" 2>/dev/null <<'P'
import json, sys
doc = json.load(open(sys.argv[1]))
v = doc.get(sys.argv[2])
if isinstance(v, dict):
    v = v.get("version")
print(str(v).strip().lstrip("vV") if v else "")
P
}

# This variant's own include/exclude, if the pointer used the object form. Silent and
# empty when there is no pointer file, when the variant used the plain string form, or
# when the key is absent - all of which mean "no fleet-wide rule, use the release's".
pointer_list() {
    python3 - "$POINTER_FILE" "$VARIANT" "$1" 2>/dev/null <<'P'
import json, sys
try:
    doc = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
v = doc.get(sys.argv[2])
if isinstance(v, dict):
    print("\n".join(str(x) for x in (v.get(sys.argv[3]) or []) if str(x).strip()))
P
}

# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------
if [[ "$MODE" == "list" ]]; then
    [[ -n "$VARIANT" ]] || VARIANT="$(detect_variant)"
    published_versions
    exit 0
fi

# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------
if [[ "$MODE" == "status" ]]; then
    ROLLBACK_TO=""
    if [[ -d "$ROLLBACK_DIR" ]]; then
        ROLLBACK_TO="$(ls -1 "$ROLLBACK_DIR" 2>/dev/null | head -1)"
    fi
    python3 - "$STATE_FILE" "$VARIANT" "$INSTALLED" "$PIN" "$ENABLED" "$ROLLBACK_TO" <<'STATUS'
import json, sys
state_path, variant, installed, pin, enabled, rollback_to = sys.argv[1:7]
try:
    state = json.load(open(state_path))
except Exception:
    state = {}
json.dump({
    "variant": variant,
    "installed": installed,
    "pinned": pin,
    "enabled": enabled.lower() == "true",
    "rollback_to": rollback_to,
    "last_result": state.get("result", ""),
    "last_message": state.get("message", ""),
    "needs_attention": state.get("needs_attention", ""),
    "last_checked": state.get("at", ""),
}, sys.stdout, indent=2, ensure_ascii=False)
print()
STATUS
    exit 0
fi

# ---------------------------------------------------------------------------
# Restart and verify - shared by the update path and the rollback path
# ---------------------------------------------------------------------------
# Prove the countdown starts on the code that was just installed, without putting a
# window on the display. "offscreen" is a real Qt platform plugin - the app constructs
# its widgets, loads the prayer map and reaches its first paint exactly as it would on
# screen, but nothing is ever mapped to :0. It is the same plugin the off-device tests
# use to drive these apps headlessly.
#
# This is what lets an interactive update leave the screen alone: the countdown is
# verified in the background and then killed, and the user relaunches it when they are
# finished with the Settings app.
verify_gui_offscreen() {
    local pid rc=0
    : > "$GUI_VERIFY_LOG"
    # Not setsid: $! has to be the python process itself so it can be watched and killed.
    QT_QPA_PLATFORM=offscreen python3 "$GUI_MAIN" >> "$GUI_VERIFY_LOG" 2>&1 &
    pid=$!
    sleep "$GUI_VERIFY_SECONDS"

    if ! kill -0 "$pid" 2>/dev/null; then
        # It exited on its own inside the settle window, which for a countdown that is
        # supposed to run forever means it crashed.
        log "  the countdown exited on its own during the offscreen check"
        rc=1
    else
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi

    if grep -q "Traceback" "$GUI_VERIFY_LOG" 2>/dev/null; then
        log "  the countdown raised an exception during the offscreen check:"
        grep -m1 -A4 "Traceback" "$GUI_VERIFY_LOG" >> "$LOG_FILE" 2>/dev/null || true
        rc=1
    fi

    [[ $rc -eq 0 ]] && log "  countdown starts cleanly on the new code (offscreen check)"
    return $rc
}

restart_apps() {
    log "Restarting the athan service..."
    sudo -n systemctl restart "$SERVICE" 2>>"$LOG_FILE" \
        || log "WARNING: could not restart $SERVICE"

    # The old countdown process is holding the previous version's code either way, so it
    # goes. What differs is whether we put it back on the screen.
    pkill -f "prayer_times_gui/main.py" 2>/dev/null || true
    sleep 2

    if [[ "$MODE" == "cron" ]]; then
        # Nobody is at the screen at 02:00, and the countdown is what the device is for -
        # so it goes straight back up. The autostart entry only fires at login, so killing
        # it does not bring it back; it has to be relaunched with that entry's environment.
        log "Restarting the prayer times GUI..."
        DISPLAY=:0 QT_QPA_PLATFORM=xcb setsid python3 "$GUI_MAIN" >> "$GUI_LOG" 2>&1 &
        disown 2>/dev/null || true
    else
        # An interactive run is driven from the fullscreen Settings app. Relaunching the
        # countdown here would map it straight over that window, and closing it - the
        # natural thing to do - would make the health check find no GUI and roll a good
        # release back. So it stays down, is verified offscreen instead, and the user
        # launches it when they are done.
        log "Leaving the countdown closed - it is checked offscreen and relaunched by you"
    fi
}

verify_healthy() {
    log "Waiting for the apps to settle..."
    sleep "$HEALTH_SETTLE_SECONDS"

    local args=()
    if [[ "$MODE" != "cron" ]]; then
        # The countdown is deliberately not on the screen during an interactive run, so
        # the on-screen checks would fail for a reason that says nothing about the
        # release. verify_gui_offscreen below covers the same ground more strictly - it
        # starts the app from scratch rather than looking at one that is already up.
        args+=(--no-gui)
    fi

    if ! bash "$SCRIPTS_DIR/health_check.sh" "${args[@]+"${args[@]}"}" >> "$LOG_FILE" 2>&1; then
        log "Health check FAILED"
        return 1
    fi

    if [[ "$MODE" != "cron" ]] && ! verify_gui_offscreen; then
        log "Health check FAILED"
        return 1
    fi

    log "Health check passed"
    return 0
}

restore_backup() {
    local version="$1"
    local source="$ROLLBACK_DIR/$version"
    [[ -d "$source" ]] || { log "ERROR: no backup for $version"; return 1; }
    log "Restoring $version from $source"
    # -a keeps the copy faithful; no --delete, so anything the failed release added and
    # the backup does not know about is left rather than guessed at.
    rsync -a "$source/" "$MAIN_DIR/" >> "$LOG_FILE" 2>&1
}

# ---------------------------------------------------------------------------
# --rollback
# ---------------------------------------------------------------------------
if [[ "$MODE" == "rollback" ]]; then
    PREVIOUS="$(ls -1 "$ROLLBACK_DIR" 2>/dev/null | head -1)"
    if [[ -z "$PREVIOUS" ]]; then
        log "Nothing to roll back to"
        write_state "error" "no retained backup" ""
        exit 1
    fi
    log "==== Rolling back to $PREVIOUS ===="
    restore_backup "$PREVIOUS" || exit 1
    echo "$PREVIOUS" > "$INSTALLED_VERSION_FILE"
    INSTALLED="$PREVIOUS"
    restart_apps
    if verify_healthy; then
        write_state "rolled_back" "restored $PREVIOUS" ""
        log "==== Rolled back to $PREVIOUS ===="
        exit 0
    fi
    write_state "error" "rolled back to $PREVIOUS but it is unhealthy" ""
    exit 1
fi

# ---------------------------------------------------------------------------
# Should we run at all?
# ---------------------------------------------------------------------------
# Named out loud, because the two modes end differently on the screen and a log that
# does not say which one ran cannot explain what the device did.
case "$MODE" in
    cron) log "Run mode: cron (unattended - the countdown is restarted on the screen)" ;;
    now)  log "Run mode: now (Settings app - the countdown stays closed and is checked offscreen)" ;;
esac

if [[ "$MODE" == "cron" && "${ENABLED,,}" != "true" ]]; then
    log "Updates are disabled on this device (ENABLED=$ENABLED)"
    exit 0
fi

# Never cut an athan off mid-word. A tap on "update now" is still a request to update,
# not a request to interrupt the call to prayer, so this applies in both modes.
if pgrep -x cvlc > /dev/null 2>&1 || pgrep -f "play_audio.sh" > /dev/null 2>&1; then
    log "Audio is playing - leaving this for the next run"
    exit 0
fi

HARDWARE_VARIANT="$(detect_variant)"
if [[ -z "$VARIANT" ]]; then
    VARIANT="$HARDWARE_VARIANT"
    log "No VARIANT in update.conf - using the hardware's answer: ${VARIANT:-unknown}"
fi
if [[ -z "$VARIANT" ]]; then
    log "ERROR: cannot tell which build this device takes - set VARIANT in $UPDATE_CONF"
    write_state "error" "variant unknown" ""
    exit 1
fi
if [[ -n "$HARDWARE_VARIANT" && "$HARDWARE_VARIANT" != "$VARIANT" ]]; then
    log "ERROR: update.conf says VARIANT=$VARIANT but this is a $HARDWARE_VARIANT."
    log "       Refusing to update - a card cloned from the other device looks like this."
    write_state "error" "variant mismatch: conf=$VARIANT hardware=$HARDWARE_VARIANT" ""
    exit 1
fi

# ---------------------------------------------------------------------------
# Which version are we heading for?
# ---------------------------------------------------------------------------
# Fetched here whatever the mode, because even a pinned or hand-targeted run wants this
# variant's path rules out of it. A pin is a decision about which version, not about
# which files a release is allowed to replace.
POINTER_OK=1
fetch_pointer || POINTER_OK=0

if [[ -n "$TARGET_ARG" ]]; then
    TARGET="$TARGET_ARG"
    log "Target $TARGET (asked for directly)"
elif [[ -n "$PIN" ]]; then
    TARGET="$PIN"
    log "Target $TARGET (pinned in update.conf)"
else
    # One central file decides this, not "whichever release is newest" - so a release can
    # be published and tested on one device before the fleet is pointed at it, and one
    # edit puts everyone back.
    if [[ $POINTER_OK -eq 0 ]]; then
        log "Cannot read the version pointer at $UPDATE_POINTER_URL"
        log "       Staying on $INSTALLED and trying again on the next run."
        write_state "no_pointer" "version pointer unreachable" "keep"
        exit 0
    fi
    TARGET="$(pointer_version)"
    if [[ -z "$TARGET" ]]; then
        log "The version pointer names no version for variant '$VARIANT' - nothing to install"
        write_state "no_release" "pointer names no $VARIANT version" "keep"
        exit 0
    fi
    log "Target $TARGET (version pointer)"
fi

# A --target or pinned run is allowed to continue without the pointer, so that a device
# can still be recovered by hand when the pointer is malformed. It has to be loud: the
# fleet-wide path rules are not being applied to this run.
if [[ $POINTER_OK -eq 0 ]]; then
    log "WARNING: the version pointer could not be read - applying this release with the"
    log "         manifest's path rules only, without any fleet-wide include/exclude."
fi

if [[ "$TARGET" == "$INSTALLED" ]]; then
    log "Already on $TARGET - nothing to do"
    write_state "up_to_date" "" "keep"
    exit 0
fi

TAG="${VARIANT}-v${TARGET}"
log "==== Updating $INSTALLED -> $TARGET ($TAG) ===="

# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
MANIFEST="$UPDATE_DIR/version.json"

if ! curl -fsSL "$UPDATE_DOWNLOAD_URL/$TAG/version.json" -o "$MANIFEST" 2>>"$LOG_FILE"; then
    log "ERROR: no manifest for $TAG"
    write_state "error" "no manifest for $TAG" ""
    exit 1
fi

M_VARIANT="$(json_field "$MANIFEST" variant)"
M_VERSION="$(json_field "$MANIFEST" version)"
M_ARCHIVE="$(json_field "$MANIFEST" archive)"
M_SHA256="$(json_field "$MANIFEST" sha256)"
M_MIN_UPDATER="$(json_field "$MANIFEST" min_updater)"
M_APPLY_MODE="$(json_field "$MANIFEST" apply_mode)"

if [[ "$M_VARIANT" != "$VARIANT" ]]; then
    log "ERROR: this release is for '$M_VARIANT', this device is '$VARIANT'"
    log "       (hardware says '${HARDWARE_VARIANT:-unknown}') - refusing before download."
    write_state "error" "variant mismatch: release=$M_VARIANT device=$VARIANT" ""
    exit 1
fi

if [[ -n "$M_MIN_UPDATER" ]]; then
    if [[ "$(printf '%s\n%s\n' "$M_MIN_UPDATER" "$UPDATER_VERSION" | sort -V | head -1)" != "$M_MIN_UPDATER" ]]; then
        log "ERROR: $TARGET needs updater $M_MIN_UPDATER, this one is $UPDATER_VERSION"
        write_state "error" "updater too old for $TARGET" "updater $M_MIN_UPDATER needed"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Download and verify
# ---------------------------------------------------------------------------
ARCHIVE="$UPDATE_DIR/$M_ARCHIVE"
log "Downloading $M_ARCHIVE..."
if ! curl -fsSL "$UPDATE_DOWNLOAD_URL/$TAG/$M_ARCHIVE" -o "$ARCHIVE" 2>>"$LOG_FILE"; then
    log "ERROR: download failed"
    write_state "error" "download failed" ""
    exit 1
fi

ACTUAL_SHA="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
if [[ "$ACTUAL_SHA" != "$M_SHA256" ]]; then
    log "ERROR: checksum mismatch - expected $M_SHA256, got $ACTUAL_SHA"
    log "       Nothing has been touched."
    rm -f "$ARCHIVE"
    write_state "error" "checksum mismatch" ""
    exit 1
fi
log "Checksum verified"

tar -xzf "$ARCHIVE" -C "$STAGING_DIR" 2>>"$LOG_FILE" || {
    log "ERROR: could not extract $M_ARCHIVE"
    write_state "error" "extract failed" ""
    exit 1
}
# git archive keeps the top-level directory name; step into it if it is there.
if [[ ! -d "$STAGING_DIR/config" ]]; then
    inner="$(find "$STAGING_DIR" -maxdepth 1 -mindepth 1 -type d | head -1)"
    [[ -n "$inner" ]] && STAGING_DIR="$inner"
fi

# ---------------------------------------------------------------------------
# Pre-flight - fail before anything on the device is touched
# ---------------------------------------------------------------------------
log "Checking the downloaded tree..."
if ! find "$STAGING_DIR" -name '*.py' -print0 | xargs -0 -r python3 -m py_compile 2>>"$LOG_FILE"; then
    log "ERROR: a Python file in $TARGET does not compile - refusing it"
    write_state "error" "$TARGET has a Python syntax error" ""
    exit 1
fi
while IFS= read -r script; do
    if ! bash -n "$script" 2>>"$LOG_FILE"; then
        log "ERROR: $script does not parse - refusing $TARGET"
        write_state "error" "$TARGET has a shell syntax error" ""
        exit 1
    fi
done < <(find "$STAGING_DIR" -name '*.sh')
log "Downloaded tree parses"

# The payload carries the template user. Rewriting it here, in staging, means the live
# tree is never even briefly pointing at a home that does not exist.
bash "$STAGING_DIR/config/scripts/set_device_user.sh" "$STAGING_DIR" >> "$LOG_FILE" 2>&1 \
    || log "WARNING: could not set the device user on the staged tree"

# ---------------------------------------------------------------------------
# Which paths are we replacing?
# ---------------------------------------------------------------------------
# The full resolution, in the order the layers are applied:
#
#   (manifest.include + pointer.include)
#     - manifest.exclude - pointer.exclude - EXTRA_EXCLUDE - DENY_LIST
#
# The release describes its own tree, so it is the baseline. The pointer layers this
# variant's fleet-wide policy on top, which is what lets one hardware protect or claim a
# path without cutting a release. The device's own EXTRA_EXCLUDE and the hard-coded
# deny-list subtract last and cannot be argued with.
mapfile -t INCLUDES < <(json_list "$MANIFEST" include)
mapfile -t M_EXCLUDES < <(json_list "$MANIFEST" exclude)
mapfile -t P_INCLUDES < <(pointer_list include)
mapfile -t P_EXCLUDES < <(pointer_list exclude)

if [[ ${#INCLUDES[@]} -eq 0 ]]; then
    log "ERROR: the manifest names no paths to install"
    write_state "error" "manifest has no include list" ""
    exit 1
fi

# Being central buys the pointer no extra trust: its include list faces exactly the same
# refusal as a release's, and the deny-list below outranks both.
refuse_if_protected() { # $1 path, $2 where it came from, $3 state message prefix
    local inc="$1" origin="$2" prefix="$3" denied match
    for denied in "audio/" "var/" "logs/" "config/config.ini" "config/update.conf"; do
        # A directory denies everything beneath it; a file denies only itself. Matching
        # on a bare prefix would read "config/update.conf.example" as "config/update.conf"
        # and refuse a release for shipping its own example file.
        if [[ "${denied%/}" == "$denied" ]]; then
            match=$([[ "$inc" == "$denied" ]] && echo yes || echo no)
        else
            match=$([[ "$inc" == "$denied" || "$inc" == "$denied"* ]] && echo yes || echo no)
        fi
        if [[ "$match" == "yes" ]]; then
            log "ERROR: $origin asks to replace '$inc', which is device data."
            log "       Refusing the whole update - nothing has been touched."
            write_state "error" "$prefix names protected path: $inc" ""
            exit 1
        fi
    done
}

for inc in "${INCLUDES[@]}"; do
    refuse_if_protected "$inc" "this release" "manifest"
done
for inc in ${P_INCLUDES[@]+"${P_INCLUDES[@]}"}; do
    refuse_if_protected "$inc" "the version pointer" "pointer"
done

# Additions, not a replacement. The manifest's list is generated by make_release.sh from
# the same list its strip step checks, which is what keeps the archive and the path list
# honest; discarding it here would break that, and would misapply a new list to an old
# archive during a rollback.
for inc in ${P_INCLUDES[@]+"${P_INCLUDES[@]}"}; do
    already=0
    for existing in "${INCLUDES[@]}"; do
        [[ "$existing" == "$inc" ]] && already=1 && break
    done
    if [[ $already -eq 0 ]]; then
        INCLUDES+=("$inc")
        log "  adding $inc (named by the version pointer)"
    fi
done

ALL_EXCLUDES=("${DENY_LIST[@]}" "${M_EXCLUDES[@]}" ${P_EXCLUDES[@]+"${P_EXCLUDES[@]}"} ${EXTRA_EXCLUDE:-})
RSYNC_EXCLUDES=()
for pattern in "${ALL_EXCLUDES[@]}"; do
    [[ -n "$pattern" ]] && RSYNC_EXCLUDES+=(--exclude="$pattern")
done

path_excluded() {
    local path="$1" pattern
    for pattern in "${ALL_EXCLUDES[@]}"; do
        [[ -z "$pattern" ]] && continue
        if [[ "${pattern%/}" != "$pattern" ]]; then
            [[ "$path" == "$pattern"* || "${path%/}" == "${pattern%/}" ]] && return 0
        else
            # shellcheck disable=SC2053
            [[ "$path" == $pattern || "${path%/}" == "$pattern" ]] && return 0
        fi
    done
    return 1
}

# An excluded entry has to leave the include list, not merely be handed to rsync as an
# --exclude. Where the entry is a single file, rsync matches its patterns against the
# name of that file alone, so "config/pipewire-pulse.conf" never matches and the file
# would be replaced despite being excluded.
# With four layers able to exclude something, "why was this not replaced?" needs an
# answer in the log, or diagnosing it means reading three files on two machines.
exclusion_source() {
    local path="$1" p
    for p in ${EXTRA_EXCLUDE:-};                          do [[ "$path" == "$p" ]] && { echo "this device's EXTRA_EXCLUDE"; return; }; done
    for p in ${P_EXCLUDES[@]+"${P_EXCLUDES[@]}"};         do [[ "$path" == "$p" ]] && { echo "the version pointer"; return; }; done
    for p in ${M_EXCLUDES[@]+"${M_EXCLUDES[@]}"};         do [[ "$path" == "$p" ]] && { echo "the release"; return; }; done
    echo "the deny-list"
}

EFFECTIVE_INCLUDES=()
for inc in "${INCLUDES[@]}"; do
    if path_excluded "$inc"; then
        log "  keeping this device's own $inc (excluded by $(exclusion_source "$inc"))"
        continue
    fi
    EFFECTIVE_INCLUDES+=("$inc")
done
if [[ ${#EFFECTIVE_INCLUDES[@]} -eq 0 ]]; then
    log "Everything this release offers is excluded on this device - nothing to do"
    write_state "up_to_date" "all paths excluded locally" "keep"
    exit 0
fi

EFFECTIVE_MODE="${APPLY_MODE:-${M_APPLY_MODE:-changed}}"
log "Apply mode: $EFFECTIVE_MODE"
log "Replacing: ${EFFECTIVE_INCLUDES[*]}"
log "Protecting: ${DENY_LIST[*]} ${M_EXCLUDES[*]} ${P_EXCLUDES[*]-} ${EXTRA_EXCLUDE:-}"

# ---------------------------------------------------------------------------
# Back up, then swap
# ---------------------------------------------------------------------------
BACKUP="$ROLLBACK_DIR/$INSTALLED"
rm -rf "$ROLLBACK_DIR"; mkdir -p "$BACKUP"
log "Backing up the current version to $BACKUP"
for inc in "${EFFECTIVE_INCLUDES[@]}"; do
    src="$MAIN_DIR/${inc%/}"
    [[ -e "$src" ]] || continue
    mkdir -p "$BACKUP/$(dirname "${inc%/}")"
    rsync -a "${RSYNC_EXCLUDES[@]}" "$src" "$BACKUP/$(dirname "${inc%/}")/" >> "$LOG_FILE" 2>&1
done

RSYNC_FLAGS=(-a --checksum)
[[ "$EFFECTIVE_MODE" == "full" ]] && RSYNC_FLAGS+=(--delete)

log "Installing $TARGET..."
FAILED=0
for inc in "${EFFECTIVE_INCLUDES[@]}"; do
    src="$STAGING_DIR/${inc%/}"
    if [[ ! -e "$src" ]]; then
        log "  skipping $inc - not in this release"
        continue
    fi
    dest="$MAIN_DIR/$(dirname "${inc%/}")/"
    mkdir -p "$dest"
    if [[ -d "$src" ]]; then
        rsync "${RSYNC_FLAGS[@]}" "${RSYNC_EXCLUDES[@]}" "$src/" "$MAIN_DIR/${inc%/}/" >> "$LOG_FILE" 2>&1 || FAILED=1
    else
        rsync "${RSYNC_FLAGS[@]}" "${RSYNC_EXCLUDES[@]}" "$src" "$dest" >> "$LOG_FILE" 2>&1 || FAILED=1
    fi
    log "  $inc"
done

if [[ $FAILED -eq 1 ]]; then
    log "ERROR: install failed part way - restoring $INSTALLED"
    restore_backup "$INSTALLED"
    restart_apps
    write_state "error" "install failed, restored $INSTALLED" ""
    exit 1
fi

# ---------------------------------------------------------------------------
# Anything that needs root is reported, never attempted
# ---------------------------------------------------------------------------
# Copying unit files into /etc or installing fonts needs root, and cron has no terminal
# to answer a sudo prompt. Granting NOPASSWD for those would be a root grant in all but
# name, for something that changes on first install and almost never again.
ATTENTION=""
for unit in "$STAGING_DIR"/config/systemd/*.service; do
    [[ -f "$unit" ]] || continue
    installed_unit="/etc/systemd/system/$(basename "$unit")"
    if [[ ! -f "$installed_unit" ]] || ! diff -q "$unit" "$installed_unit" > /dev/null 2>&1; then
        ATTENTION="systemd unit changed: $(basename "$unit")"
        log "NOTE: $ATTENTION - run init.sh to install it"
    fi
done

# ---------------------------------------------------------------------------
# Rebuild, restart, verify
# ---------------------------------------------------------------------------
log "Rebuilding the prayer times map from this device's own CSV..."
bash "$SCRIPTS_DIR/apply_settings.sh" >> "$LOG_FILE" 2>&1 \
    || log "WARNING: apply_settings.sh did not finish cleanly"

restart_apps

if verify_healthy; then
    echo "$TARGET" > "$INSTALLED_VERSION_FILE"
    INSTALLED="$TARGET"
    rm -rf "$STAGING_DIR" "$ARCHIVE"
    write_state "updated" "installed $TARGET" "$ATTENTION"
    log "==== Updated to $TARGET ===="
    exit 0
fi

log "ERROR: $TARGET is unhealthy - putting $INSTALLED back"
if restore_backup "$INSTALLED"; then
    restart_apps
    if verify_healthy; then
        log "==== Rolled back to $INSTALLED - it is healthy again ===="
        write_state "rolled_back" "$TARGET was unhealthy, restored $INSTALLED" ""
    else
        log "==== Rolled back to $INSTALLED but it is STILL unhealthy ===="
        write_state "error" "$TARGET failed and $INSTALLED is unhealthy too" "manual repair needed"
    fi
fi
# installed_version is deliberately left alone, so the next run tries again.
exit 1
