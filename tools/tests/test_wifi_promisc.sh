#!/bin/bash
# The watchdog's promiscuous-mode step, run without root and without touching wlan0.
#
# The watchdog is one long loop with no entry point to call into, so the function is cut
# out of the real script and run against a stub ip and a fake /sys/class/net - the code
# under test is the code that ships, not a copy of it.
#
#   bash tools/tests/test_wifi_promisc.sh
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
mkdir -p "$ROOT/sys/wlan0"

cat > "$ROOT/ip" <<'STUB'
#!/bin/bash
echo "$*" >> "$CALLS"
exit "${IP_RC:-0}"
STUB
chmod +x "$ROOT/ip"

FUNC="$(sed -n '/^IFF_PROMISC=/,/^}/p' "$SRC")"

run() {
    : > "$ROOT/calls"; : > "$ROOT/log"
    CALLS="$ROOT/calls" IP_RC="${2:-0}" NET_SYSFS="$ROOT/sys" bash -c "
        IP='$ROOT/ip'; INTERFACE=\"\$1\"
        log() { echo \"\$1\" >> '$ROOT/log'; }
        $FUNC
        ensure_promisc
    " _ "$1"
    echo $?
}

echo "promiscuous mode"

echo 0x1003 > "$ROOT/sys/wlan0/flags"
chk "off: switched on"            "$(run wlan0)"           "0"
chk "off: ip asked for promisc"   "$(cat "$ROOT/calls")"   "link set wlan0 promisc on"
chk "off: logged"                 "$(cat "$ROOT/log")"     "Promiscuous mode switched on for wlan0"

echo 0x1103 > "$ROOT/sys/wlan0/flags"
chk "already on: ok"              "$(run wlan0)"           "0"
chk "already on: ip not called"   "$(cat "$ROOT/calls")"   ""
chk "already on: nothing logged"  "$(cat "$ROOT/log")"     ""

echo 0x1003 > "$ROOT/sys/wlan0/flags"
chk "ip fails: reported"          "$(run wlan0 2)"         "1"
chk "ip fails: warning logged"    "$(cat "$ROOT/log")"     "WARNING: could not switch on promiscuous mode for wlan0"

chk "no such interface: fails"    "$(run wlan9)"           "1"
chk "no such interface: ip not called" "$(cat "$ROOT/calls")" ""

echo "wiring"
chk "set once at startup" \
    "$(grep -c '^ensure_promisc$' "$SRC")" "1"
chk "re-checked on every loop tick, before the health check" \
    "$(awk '/^while true; do/{w=1;next} w&&NF{print;exit}' "$SRC" | tr -d ' ')" "ensure_promisc"
chk "script parses" "$(bash -n "$SRC" && echo ok)" "ok"

echo
if [[ ${#fails[@]} -eq 0 ]]; then
    echo "all passed"
else
    echo "${#fails[@]} failed"
    exit 1
fi
