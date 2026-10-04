#!/bin/bash
# config/scripts/set_wallpaper.sh: the desktop background, set once per shipped picture.
# Runs on a copy of the tree with a fake HOME and a stand-in pcmanfm, so neither this
# machine's desktop nor the repo is touched.
#
#   bash tools/tests/test_wallpaper.sh
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TREE="$REPO_ROOT/scheduler-official-touch-screen-with-raspberry-pi-4"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail=0
chk() { if [ "$2" = "$3" ]; then echo "  ✓ $1"; else echo "  ✗ $1 — expected $3, got $2"; fail=1; fi; }

HOME_DIR="$WORK/home"
SCHED="$HOME_DIR/Desktop/scheduler"
mkdir -p "$SCHED/config/wallpaper" "$SCHED/config/scripts" "$WORK/run" "$WORK/bin"
cp "$TREE/config/wallpaper/sakina-wallpaper.jpg" "$SCHED/config/wallpaper/"
cp "$TREE/config/scripts/set_wallpaper.sh" "$SCHED/config/scripts/"
PICTURE="$SCHED/config/wallpaper/sakina-wallpaper.jpg"
CONF="$HOME_DIR/.config/pcmanfm/default/desktop-items-DSI-1.conf"

# Records how it was called, the way the real one is told over its socket.
cat > "$WORK/bin/pcmanfm" << EOF
#!/bin/bash
echo "DISPLAY=\$DISPLAY \$*" >> "$WORK/pcmanfm.calls"
EOF
chmod +x "$WORK/bin/pcmanfm"

run() {
    env -i HOME="$HOME_DIR" PATH="$WORK/bin:/usr/bin:/bin" XDG_RUNTIME_DIR="$WORK/run" \
        bash "$SCHED/config/scripts/set_wallpaper.sh"
}
wallpaper() { grep '^wallpaper=' "$1" | cut -d= -f2-; }

echo "1. no desktop running: the config the desktop reads at start"
mkdir -p "$(dirname "$CONF")"
printf '[*]\nwallpaper_mode=fit\nwallpaper_common=1\nwallpaper=/usr/share/rpd-wallpaper/sunrise.jpg\ndesktop_bg=#d6d3de\n\n[prayer_times_gui.desktop]\nx=122\ny=226\n' > "$CONF"
chk "says so" "$(run)" "Wallpaper set for the next time the desktop starts"
chk "the picture is named" "$(wallpaper "$CONF")" "$PICTURE"
chk "cropped to the screen" "$(grep '^wallpaper_mode=' "$CONF")" "wallpaper_mode=crop"
chk "the icon positions are kept" "$(grep -c '^x=122' "$CONF")" "1"
chk "pcmanfm was not started" "$([ -f "$WORK/pcmanfm.calls" ] && echo called || echo no)" "no"

echo "2. once per picture: the owner's own choice stays"
sed -i 's|^wallpaper=.*|wallpaper=/home/owner/own.jpg|' "$CONF"
chk "a second run leaves it" "$(run)" "Wallpaper already set"
chk "the owner's picture survives" "$(wallpaper "$CONF")" "/home/owner/own.jpg"
echo "new" >> "$PICTURE"
run > /dev/null
chk "a new shipped picture is set again" "$(wallpaper "$CONF")" "$PICTURE"

echo "3. with the desktop running it is told over its socket"
touch "$WORK/run/pcmanfm-socket--0"
echo "newer" >> "$PICTURE"
chk "says so" "$(run)" "Wallpaper set on the running desktop"
chk "on the display the socket names" "$(cat "$WORK/pcmanfm.calls")" \
    "DISPLAY=:0 --set-wallpaper=$PICTURE --wallpaper-mode=crop"

echo "4. a device that never started the desktop gets a config of its own"
rm -rf "$HOME_DIR/.config" "$WORK/run/pcmanfm-socket--0" "$SCHED/var"
run > /dev/null
chk "the default profile names it" "$(wallpaper "$HOME_DIR/.config/pcmanfm/default/desktop-items-0.conf")" "$PICTURE"

echo "5. never fatal"
rm "$PICTURE" "$SCHED/var/wallpaper_for"
run > "$WORK/log"
chk "no picture: exit 0" "$?" "0"
chk "and says why" "$(grep -c "missing - skipped" "$WORK/log")" "1"

echo
[ "$fail" -eq 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
