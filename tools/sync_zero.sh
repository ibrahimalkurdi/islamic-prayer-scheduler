#!/bin/bash
# Makes the Zero's tree the Pi 4's tree, apart from what only the Zero has.
#
# The two devices run one app: the Pi 4 tree is where it is written, and the Zero takes
# every file it tracks. What the Zero keeps for itself is the short list below - the scale
# for its 1024x600 panel among them - and what it never takes is the Pi
# 4's Wi-Fi watchdog: the Zero is kept reachable by a dispatcher script instead.
#
#   tools/sync_zero.sh            copy, then list what changed
#   tools/sync_zero.sh --check    exit 1 and list the differences if the trees disagree
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PI4="scheduler-official-touch-screen-with-raspberry-pi-4"
ZERO="scheduler-unofficial-touch-screen-with-raspberry-zero"
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

# The Zero's own: its README and photos describe its hardware, display.ini scales the
# apps for its panel, and the other two make the Pi 4's setup behave as the Zero
# needs (see system_apply.sh).
zero_owned() {
    case "$1" in
        README.md|assets/raspberry-pi-zero-*|assets/raspberry-pi-5-*) return 0 ;;
        config/NetworkManager/*|config/units-off.txt|config/display.ini) return 0 ;;
    esac
    return 1
}

# The Pi 4's own, never copied.
pi4_only() {
    case "$1" in
        assets/raspberry-pi-4-*) return 0 ;;
        config/scripts/wifi_connectivity_resolver.sh) return 0 ;;
        config/systemd/wifi_connectivity_resolver.service) return 0 ;;
    esac
    return 1
}

cd "$REPO" || exit 2
differences=()
while IFS= read -r -d "" path; do
    rel="${path#$PI4/}"
    pi4_only "$rel" && continue
    zero_owned "$rel" && continue
    [[ -f "$path" ]] || continue
    target="$ZERO/$rel"
    if ! cmp -s "$path" "$target" || [[ "$(stat -c %a "$path")" != "$(stat -c %a "$target" 2> /dev/null)" ]]; then
        differences+=("copy   $rel")
        if [[ $CHECK -eq 0 ]]; then
            mkdir -p "$(dirname "$target")"
            cp -p "$path" "$target"
        fi
    fi
done < <(git ls-files -z --cached --others --exclude-standard "$PI4")

while IFS= read -r -d "" path; do
    rel="${path#$ZERO/}"
    zero_owned "$rel" && continue
    [[ -f "$PI4/$rel" ]] && ! pi4_only "$rel" && continue
    [[ -e "$path" ]] || continue
    differences+=("remove $rel")
    [[ $CHECK -eq 0 ]] && rm -f "$path"
done < <(git ls-files -z --cached --others --exclude-standard "$ZERO")
[[ $CHECK -eq 0 ]] && find "$ZERO" -mindepth 1 -type d -empty -delete

if [[ ${#differences[@]} -eq 0 ]]; then
    echo "The Zero tree matches the Pi 4 tree."
    exit 0
fi
printf '%s\n' "${differences[@]}"
if [[ $CHECK -eq 1 ]]; then
    echo "The Zero tree is behind the Pi 4 tree - run tools/sync_zero.sh" >&2
    exit 1
fi
echo "${#differences[@]} file(s) changed in $ZERO - review with git status, then commit."
