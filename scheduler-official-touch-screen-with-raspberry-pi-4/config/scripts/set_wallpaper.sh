#!/bin/bash
# The desktop background: config/wallpaper/sakina-wallpaper.jpg.
#
# Run by check_updates.sh after a healthy update and by init.sh. Set once per picture -
# the stamp holds the hash of the one last set - so an owner who picks a background of
# their own keeps it until a release ships a new picture.
#
# The desktop is pcmanfm's. With the session running it is told over its socket, which
# saves the choice in its own config and repaints at once. Without one - setup from a
# terminal before the first login, or no desktop at all - the config files are edited and
# the desktop reads them when it starts. Never fatal: a background is not worth failing
# an update over.
set -uo pipefail

BASE_DIR="${SCHEDULER_DIR:-$HOME/Desktop/scheduler}"
PICTURE="$BASE_DIR/config/wallpaper/sakina-wallpaper.jpg"
STAMP="$BASE_DIR/var/wallpaper_for"
PCMANFM_CONFIG="${PCMANFM_CONFIG:-$HOME/.config/pcmanfm}"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
MODE="crop"

[[ -f "$PICTURE" ]] || { echo "Wallpaper: $PICTURE is missing - skipped"; exit 0; }

WANT="$(sha256sum < "$PICTURE" | cut -c1-64)"
if [[ "$(cat "$STAMP" 2> /dev/null)" == "$WANT" ]]; then
    echo "Wallpaper already set"
    exit 0
fi

set_in_config() {
    local file found=0
    # The desktop keeps one file per screen, named after it. A device that has never
    # started the desktop has none yet: the profile's own default is the one it reads.
    for file in "$PCMANFM_CONFIG"/*/desktop-items-*.conf; do
        [[ -f "$file" ]] || continue
        found=1
        sed -i -e "s|^wallpaper=.*|wallpaper=$PICTURE|" -e "s|^wallpaper_mode=.*|wallpaper_mode=$MODE|" "$file"
        grep -q '^wallpaper=' "$file" || sed -i "/^\[\*\]\$/a wallpaper=$PICTURE" "$file"
        grep -q '^wallpaper_mode=' "$file" || sed -i "/^\[\*\]\$/a wallpaper_mode=$MODE" "$file"
    done
    if [[ "$found" -eq 0 ]]; then
        mkdir -p "$PCMANFM_CONFIG/default"
        printf '[*]\nwallpaper_mode=%s\nwallpaper_common=1\nwallpaper=%s\n' "$MODE" "$PICTURE" \
            > "$PCMANFM_CONFIG/default/desktop-items-0.conf"
    fi
}

# pcmanfm names its socket after the X display it serves: :0 is pcmanfm-socket--0.
SOCKET="$(ls "$RUNTIME_DIR"/pcmanfm-socket--* 2> /dev/null | head -n 1)"
if [[ -n "$SOCKET" ]] && command -v pcmanfm > /dev/null \
    && DISPLAY=":${SOCKET##*--}" XDG_RUNTIME_DIR="$RUNTIME_DIR" \
        timeout 20 pcmanfm --set-wallpaper="$PICTURE" --wallpaper-mode="$MODE" > /dev/null 2>&1; then
    echo "Wallpaper set on the running desktop"
else
    set_in_config
    echo "Wallpaper set for the next time the desktop starts"
fi

mkdir -p "$(dirname "$STAMP")"
echo "$WANT" > "$STAMP"
