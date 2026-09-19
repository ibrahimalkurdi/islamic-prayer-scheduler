#!/bin/bash
# The question the whole design exists to answer: after a real update lands, is the
# owner's own data still exactly as it was?
#
# Run after make_fixture.sh, from inside the fixture directory. Re-runnable.
HERE="$(cd "$(dirname "$0")" && pwd)"
DEV="$HERE/dev"; SCH="$DEV/Desktop/scheduler"
GUI_MAIN="$SCH/applications/desktop/prayer_times_gui/main.py"
fail=0

chk() { # name, condition-output, expected
    if [[ "$2" == "$3" ]]; then echo "  ✓ $1"
    else echo "  ✗ $1  expected '$3', got '$2'"; fail=1; fi
}

# Start from 1.0.0 with nothing pinned, whatever earlier tests left behind.
echo "1.0.0" > "$SCH/var/installed_version"
python3 - "$SCH/config/update.conf" <<'P'
import re, sys
path = sys.argv[1]
text = open(path).read()
for key, value in (("PIN", ""), ("ENABLED", "true"), ("EXTRA_EXCLUDE", "")):
    text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
open(path, "w").write(text)
P

echo "Updating 1.0.0 -> 1.1.0..."
HOME="$DEV" DEVICE_MODEL_FILE="$HERE/fake_model" HEALTH_SETTLE_SECONDS=1 \
    timeout 180 bash "$SCH/config/scripts/check_updates.sh" --now > /dev/null 2>&1

echo
echo "The update landed:"
chk "installed_version says 1.1.0" "$(cat "$SCH/var/installed_version")" "1.1.0"
chk "the new code is on the device" \
    "$(grep -c 'fixture marker: version 1.1.0' "$GUI_MAIN")" "1"

echo
echo "The owner's data is untouched:"
chk "audio file byte-identical" "$(cat "$SCH/audio/fajr/athan.mp3")" "FIXTURE-AUDIO"
chk "settings kept" \
    "$(grep -c 'listen_to_quran = 04:44' "$SCH/config/config.ini")" "1"
chk "prayer map kept (config)" \
    "$(grep -c '12:34' "$SCH/config/prayer_times_map.py")" "1"
chk "prayer map kept (inside the replaced app directory)" \
    "$(grep -c '12:34' "$SCH/applications/desktop/prayer_times_gui/prayer_times_map.py")" "1"

echo
echo "The payload's template user was rewritten before anything was copied:"
leaked="$(grep -rl "/home/ihms" "$SCH" \
    --exclude-dir=logs --exclude-dir=var --exclude-dir=audio \
    --exclude='*.md' --exclude=set_device_user.sh 2>/dev/null | wc -l)"
chk "no file still points at /home/ihms" "$leaked" "0"
chk "the wifi unit still runs as root" \
    "$(grep -c '^User=root' "$SCH/config/systemd/wifi_connectivity_resolver.service" 2>/dev/null)" "1"
# cron exports HOME but not USER, and an unset USER used to write "User=" - an invalid
# unit that will not start, and one the substitution could never find again because the
# template string was already gone. Run it the way cron would.
env -i HOME="$DEV" PATH=/usr/bin:/bin \
    bash "$SCH/config/scripts/set_device_user.sh" "$SCH" > /dev/null 2>&1 || true
chk "no empty User= after a run with no \$USER" \
    "$(grep -rc '^User=$' "$SCH/config/systemd/" 2>/dev/null | grep -c ':[1-9]')" "0"
chk "the athan unit names a real user" \
    "$(grep -hc "^User=$(id -un)$" "$SCH/config/systemd/audio_event_scheduler.service" 2>/dev/null)" "1"
chk "the website unit names a real user" \
    "$(grep -hc "^User=$(id -un)$" "$SCH/config/systemd/scheduler_web_ui.service" 2>/dev/null)" "1"
# Without this capability the website cannot bind port 80 at all, and a careless
# substitution could eat it.
chk "the website unit can still bind port 80" \
    "$(grep -hc '^AmbientCapabilities=CAP_NET_BIND_SERVICE$' "$SCH/config/systemd/scheduler_web_ui.service" 2>/dev/null)" "1"
# And the unit must NOT name XDG_RUNTIME_DIR. It did once, as /run/user/%U, and on a real
# device %U resolved to 0 despite User= being set - so the service looked for PipeWire
# under root's runtime directory and every mute fell back to killing the player. mute.py
# derives it from the running process's own uid; a value here would override that and
# bring the bug back.
chk "the website unit does not hard-code a runtime directory" \
    "$(grep -hc '^Environment=XDG_RUNTIME_DIR' "$SCH/config/systemd/scheduler_web_ui.service" 2>/dev/null)" "0"
# And it must not clamp the capability bounding set. It did, to CAP_NET_BIND_SERVICE
# alone, which reads as free hardening and is not: sudo is setuid-root and calls
# setgid(0) before anything else, which needs CAP_SETGID. Inside a clamped bounding set
# becoming root grants nothing, so the save button on the website ran apply_settings.sh
# straight into "sudo: unable to change to root gid" and could never restart the athan
# service. User= is what keeps this process unprivileged; the bounding set never was.
chk "the website unit does not clamp the capability bounding set" \
    "$(grep -hc '^CapabilityBoundingSet=' "$SCH/config/systemd/scheduler_web_ui.service" 2>/dev/null)" "0"

# ---------------------------------------------------------------------------
# A desktop tap must never meet a password prompt
# ---------------------------------------------------------------------------
# The shortcut has no terminal any more, so a sudo call that asks for a password has
# nowhere to ask and hangs until somebody kills it. Every root command in init.sh goes
# through root(), which skips and reports when there is no way to prompt - except the
# helper, which is NOPASSWD and is called as sudo -n, and the three blocks that install
# the helper and the sudoers files themselves, which are guarded by CAN_PROMPT.
INIT="$SCH/config/scripts/init.sh"
# Anchored on any sudo that is not sudo -n, wherever it sits on the line. The first
# version of this check only looked at the start of a line or just after | && or ; - and
# the two sudoers blocks call it after "|| !", so both slipped through the check *and*
# through the rewrite that was supposed to convert them. A device with no terminal then
# ran sudo tee, set -e killed the script, and the desktop icon reported failure.
# [^-[:alnum:]_] keeps visudo from matching.
stray="$(grep -n '\(^\|[^-[:alnum:]_]\)sudo ' "$INIT" \
    | grep -v 'sudo -n \|sudo "\$@"' \
    | grep -vc '^[0-9]*:[[:space:]]*#')"
chk "no root command in init.sh can stall waiting for a password" "$stray" "0"
chk "the setup shortcut opens no terminal" \
    "$(grep -hc '^Terminal=false$' "$SCH/config/scheduler_setup.desktop" 2>/dev/null)" "1"
chk "the helper is only ever called non-interactively" \
    "$(grep -c 'sudo "\$SYSTEM_APPLY_INSTALLED"' "$INIT")" "0"

echo
echo "The Wi-Fi watchdog can see the failure it exists for:"
WCR="$SCH/config/scripts/wifi_connectivity_resolver.sh"
# It runs as root already. Every sudo in it opened a PAM session, several times a minute,
# for ever - all of it written to the journal and so to the SD card. Measured on a device:
# 76 PAM lines in two minutes before, 0 after.
chk "the watchdog never calls sudo" \
    "$(grep -c '^[^#]*[^-[:alnum:]_]sudo ' "$WCR" 2>/dev/null)" "0"
chk "and refuses to run as anyone but root" \
    "$(grep -c 'must run as root' "$WCR")" "1"
# The fault this device actually has: its own traffic keeps flowing while nothing on the
# LAN can open a connection to it. Pinging the router answers the wrong question and
# answered it "fine" through every hang so far.
chk "it asks whether anyone can reach the device, not just whether it can reach out" \
    "$(grep -c 'inbound_sessions' "$WCR")" "2"
chk "and re-associates only after a long silence" \
    "$(grep -c '^REASSOCIATE_AFTER=3600' "$WCR")" "1"

# The counter itself, against a table rather than against this machine's real sockets.
TCPFIX="$HERE/tcp-fixture"
mkdir -p "$TCPFIX"
cat > "$TCPFIX/tcp" <<'TCP'
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 9F02A8C0:0016 9C02A8C0:D610 01 00000000:00000000 00:00000000 00000000     0        0 0
   1: 0100007F:1F90 0100007F:C350 01 00000000:00000000 00:00000000 00000000     0        0 0
   2: 9F02A8C0:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 0
TCP
cat > "$TCPFIX/tcp6" <<'TCP6'
  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000000000000:0016 00000000000000000000000001000000:D611 01 00000000:00000000 00:00000000 00000000     0        0 0
TCP6
# Extracted rather than sourced: the file is a daemon and sourcing it would start the
# loop. One established session from a real peer, one from loopback, one listening
# socket, and one IPv6 loopback - only the first counts as somebody reaching this device.
counted="$(TCP_TABLES="$TCPFIX/tcp $TCPFIX/tcp6" bash -c "
    $(sed -n '/^inbound_sessions() {/,/^}/p' "$WCR")
    inbound_sessions")"
chk "one real peer is counted, loopback and listeners are not" "$counted" "1"
rm -rf "$TCPFIX"

echo
echo "The logs cannot fill the card:"
CRON="$SCH/config/crontab.txt"
LR="$SCH/config/logrotate/scheduler"
# Three cron lines used to blank three named logs at midnight, and missed the two that
# grew fastest - check_updates.log and web_ui.log - because nobody had named them.
chk "cron no longer blanks logs by name" \
    "$(grep -c 'echo  > .*logs/' "$CRON")" "0"
# This one is not a log. It is the record of what has played today, and emptying it at
# midnight is what starts the new day clean - rotating it would be wrong.
chk "but the daily event reset is still there" \
    "$(grep -c "echo '\[\]' > .*executed-events.json" "$CRON")" "1"
chk "a logrotate policy ships with the release" \
    "$([[ -f "$LR" ]] && echo yes || echo no)" "yes"
chk "and it matches every log, not a list of names" \
    "$(grep -c '__SCHEDULER_DIR__/logs/\*\.log {' "$LR")" "1"

if ! command -v logrotate > /dev/null 2>&1 && [[ ! -x /usr/sbin/logrotate ]]; then
    echo "  - skipped the rotation itself, no logrotate on this machine"
else
    LOGROTATE=$(command -v logrotate || echo /usr/sbin/logrotate)
    LRT="$HERE/logrotate-test"
    rm -rf "$LRT"; mkdir -p "$LRT/logs"
    sed -e "s|__SCHEDULER_DIR__|$LRT|g" -e "s|__DEVICE_USER__|$(id -un)|g" \
        "$LR" > "$LRT/conf"
    # scheduler_web_ui.service writes its log through StandardOutput=append:, so systemd
    # holds an open descriptor to it. Under the default rename-and-create that descriptor
    # would follow the rotated file and the live log would stay empty for ever - the
    # website would appear to stop logging the day rotation was switched on. This holds a
    # descriptor open across a rotation exactly as systemd does.
    exec 9>> "$LRT/logs/web_ui.log"
    echo "before-rotation" >&9
    "$LOGROTATE" -f -s "$LRT/state" "$LRT/conf" > /dev/null 2>&1
    echo "after-rotation" >&9
    exec 9>&-
    chk "a rotated log keeps taking writes from an already-open descriptor" \
        "$(grep -c 'after-rotation' "$LRT/logs/web_ui.log" 2>/dev/null)" "1"
    chk "and what was there before is kept, not dropped" \
        "$(cat "$LRT"/logs/web_ui.log.1 2>/dev/null | grep -c 'before-rotation')" "1"
    chk "the live log did not keep the old lines as well" \
        "$(grep -c 'before-rotation' "$LRT/logs/web_ui.log" 2>/dev/null)" "0"
    rm -rf "$LRT"
fi

echo
[[ $fail -eq 0 ]] && echo "ALL PASS" || echo "FAILURES ABOVE"
exit $fail
