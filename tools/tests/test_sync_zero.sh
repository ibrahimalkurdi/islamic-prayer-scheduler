#!/bin/bash
# tools/sync_zero.sh against a throwaway repo, and the real repo's two trees in step.
#
#   bash tools/tests/test_sync_zero.sh
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PI4="scheduler-official-touch-screen-with-raspberry-pi-4"
ZERO="scheduler-unofficial-touch-screen-with-raspberry-zero"

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
cd "$ROOT" || exit 2
git init -q .
mkdir -p tools "$PI4"/{applications,config/scripts,config/systemd,config/prayers-config,assets} \
         "$ZERO"/{applications,config/NetworkManager/dispatcher.d,config/old,assets}
cp "$REPO/tools/sync_zero.sh" tools/
echo "app v2" > "$PI4/applications/main.py"
printf '#!/bin/bash\n' > "$PI4/config/scripts/run.sh"; chmod 755 "$PI4/config/scripts/run.sh"
echo "berlin" > "$PI4/config/prayers-config/برلين.csv"
echo "watchdog" > "$PI4/config/scripts/wifi_connectivity_resolver.sh"
echo "[Service]" > "$PI4/config/systemd/wifi_connectivity_resolver.service"
echo "pi4 photo" > "$PI4/assets/raspberry-pi-4-board.png"
echo "pi4 readme" > "$PI4/README.md"
echo "app v1" > "$ZERO/applications/main.py"
echo "zero readme" > "$ZERO/README.md"
echo "zero photo" > "$ZERO/assets/raspberry-pi-zero-2w.png"
echo "promisc" > "$ZERO/config/NetworkManager/dispatcher.d/99-promisc"
echo "cups.service" > "$ZERO/config/units-off.txt"
echo "[screen]" > "$ZERO/config/display.ini"
echo "stale" > "$ZERO/config/old/gone.txt"
git add -A && git -c user.email=t@t -c user.name=t commit -qm init

echo "1. --check sees the trees disagree and changes nothing"
tools/sync_zero.sh --check > out.txt 2>&1; rc=$?
chk "it says so with exit 1" "$rc" "1"
chk "and leaves the Zero tree as it was" "$(cat "$ZERO/applications/main.py")" "app v1"

echo "2. a sync makes the Zero the Pi 4, apart from what is the Zero's own"
tools/sync_zero.sh > out.txt 2>&1
chk "the app is the Pi 4's" "$(cat "$ZERO/applications/main.py")" "app v2"
chk "a script keeps its executable bit" "$(stat -c %a "$ZERO/config/scripts/run.sh")" "755"
chk "a file with an Arabic name is copied" "$(cat "$ZERO/config/prayers-config/برلين.csv" 2>&1)" "berlin"
chk "the Pi 4's watchdog is not" \
    "$(ls "$ZERO/config/scripts/wifi_connectivity_resolver.sh" "$ZERO/config/systemd/wifi_connectivity_resolver.service" 2> /dev/null | wc -l)" "0"
chk "nor its board photo" "$([[ -e "$ZERO/assets/raspberry-pi-4-board.png" ]] && echo copied || echo kept-out)" "kept-out"
chk "the Zero keeps its README, photo, dispatcher script, service list and sizes" \
    "$(cat "$ZERO/README.md" "$ZERO/assets/raspberry-pi-zero-2w.png" "$ZERO/config/NetworkManager/dispatcher.d/99-promisc" "$ZERO/config/units-off.txt" "$ZERO/config/display.ini" | tr '\n' ' ')" \
    "zero readme zero photo promisc cups.service [screen] "
chk "a file the Pi 4 no longer has is removed, and its empty folder with it" \
    "$([[ -e "$ZERO/config/old" ]] && echo there || echo gone)" "gone"
tools/sync_zero.sh --check > out.txt 2>&1
chk "afterwards --check agrees" "$?" "0"

echo "3. the real repository"
"$REPO/tools/sync_zero.sh" --check > out.txt 2>&1
chk "the Zero tree is in step with the Pi 4 tree" "$?" "0"
[[ ${#fails[@]} -gt 0 ]] && head -5 out.txt

echo
if [[ ${#fails[@]} -eq 0 ]]; then echo "ALL PASS"; else echo "FAILURES: ${fails[*]}"; exit 1; fi
