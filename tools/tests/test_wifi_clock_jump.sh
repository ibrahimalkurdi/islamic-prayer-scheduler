#!/bin/bash
# The watchdog's "nobody has reached us for an hour" timer, against a fake /proc/uptime and
# a wall clock that jumps - the code under test is cut out of the real script.
#
#   bash tools/tests/test_wifi_clock_jump.sh
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO/scheduler-official-touch-screen-with-raspberry-pi-4/config/scripts/wifi_connectivity_resolver.sh"

fails=()
chk() {
    if [[ "$2" == "$3" ]]; then
        echo "  ✓ $1"
    else
        echo "  ✗ $1  expected [$3], got [$2]"
        fails+=("$1")
    fi
}

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

cat > "$ROOT/nmcli" <<'STUB'
#!/bin/bash
echo "nmcli $*" >> "$CALLS"
STUB
cat > "$ROOT/ping" <<'STUB'
#!/bin/bash
exit 0
STUB
# A wall clock that jumps by whatever $ROOT/jump holds: what a device with no clock module
# sees on its first time sync. Nothing under test may read it.
cat > "$ROOT/date" <<STUB
#!/bin/bash
echo \$(( \$(/bin/date +%s) + \$(cat "$ROOT/jump") ))
STUB
chmod +x "$ROOT/nmcli" "$ROOT/ping" "$ROOT/date"

FUNCS="$(sed -n '/^REASSOCIATE_AFTER=/,/^# --- Main Daemon Loop ---/p' "$SRC")"

# Starts the watchdog at uptime $1, then ticks once at uptime $2.
run() {
    : > "$ROOT/calls"
    echo "$1.42 100.00" > "$ROOT/uptime"
    echo 0 > "$ROOT/jump"
    CALLS="$ROOT/calls" UPTIME_FILE="$ROOT/uptime" PATH="$ROOT:$PATH" bash -c "
        NMCLI='$ROOT/nmcli'; PING='$ROOT/ping'; INTERFACE=wlan0; ROUTER=192.168.2.1
        log() { :; }
        capture_state() { :; }
        inbound_sessions() { echo 0; }
        sleep() { :; }
        $FUNCS
        echo '$2.17 100.00' > '$ROOT/uptime'
        echo $((3 * 3600)) > '$ROOT/jump'
        watch_inbound
    "
    grep -c "device disconnect" "$ROOT/calls"
}

echo "silence is measured from boot, not the wall clock"
chk "a minute of silence, wall clock jumped 3h: wifi left alone" "$(run 100 160)" "0"
chk "59 minutes of silence: left alone"                          "$(run 100 3640)" "0"
chk "an hour of silence: re-associates"                          "$(run 100 3700)" "1"

echo "wiring"
chk "no wall clock left in the watchdog" "$(grep -c 'date +%s' "$SRC")" "0"
chk "script parses" "$(bash -n "$SRC" && echo ok)" "ok"

echo
if [[ ${#fails[@]} -eq 0 ]]; then
    echo "all passed"
else
    echo "${#fails[@]} failed"
    exit 1
fi
