#!/bin/bash
# This device's own copy of the user manual, on its Desktop.
#
# The shipped USER_MANUAL_AR.pdf is built for "hostname": its cover's QR code points at
# http://hostname.local, which is the manual's placeholder, not an address. Every other
# page is the same for every device, so the device prints only a cover of its own -
# applications/manual_cover, with the date and page the shared build saved to cover.json -
# and puts it in front of the shipped pages.
#
# Run by check_updates.sh after a healthy update and by init.sh. Remade only when the
# shipped manual, the cover or the hostname changed, and never fatal: a device that cannot
# print a cover still has the shared manual, so every failure is reported and skipped,
# and the next update tries again.
#
# Needs chromium, qpdf and python3-segno; config/packages.txt brings the last two.
set -uo pipefail

BASE_DIR="${SCHEDULER_DIR:-$HOME/Desktop/scheduler}"
SHARED_PDF="$BASE_DIR/USER_MANUAL_AR.pdf"
COVER_DIR="$BASE_DIR/applications/manual_cover"
OUT="${DEVICE_MANUAL_OUT:-$HOME/Desktop/دليل-المستخدم.pdf}"
STAMP="$BASE_DIR/var/device_manual_for"
AVAHI_CONF="${AVAHI_CONF:-/etc/avahi/avahi-daemon.conf}"
# The name phones reach it by: what Avahi advertises. That is the hostname unless Avahi
# was given one of its own, as a device sharing a network with a same-named one may be.
avahi_name() {
    sed -n 's/^[[:space:]]*host-name[[:space:]]*=[[:space:]]*\([^[:space:]]*\).*/\1/p' \
        "$AVAHI_CONF" 2> /dev/null | tail -n 1
}
DEVICE="${DEVICE_MANUAL_HOST:-$(avahi_name)}"
DEVICE="${DEVICE:-$(hostname)}"
CHROMIUM="${CHROMIUM:-$(command -v chromium || command -v chromium-browser || true)}"
PYTHON="${MANUAL_PYTHON:-python3}"

skip() { echo "Device manual: $* - skipped"; exit 0; }

[[ -f "$SHARED_PDF" && -f "$COVER_DIR/cover.json" ]] || skip "no shipped manual to copy"
[[ "$DEVICE" =~ ^[A-Za-z0-9-]{1,63}$ ]] || skip "'$DEVICE' cannot be a .local name"

WANT="$DEVICE $(cat "$SHARED_PDF" "$COVER_DIR/cover.json" "$COVER_DIR/cover.html" | sha256sum | cut -c1-64)"
if [[ -f "$OUT" && "$(cat "$STAMP" 2> /dev/null)" == "$WANT" ]]; then
    echo "Device manual already up to date"
    exit 0
fi

[[ -n "$CHROMIUM" ]] || skip "chromium is not installed"
command -v qpdf > /dev/null || skip "qpdf is not installed"
"$PYTHON" -c 'import segno' 2> /dev/null || skip "python3-segno is not installed"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

"$PYTHON" "$COVER_DIR/make_cover.py" "$WORK/cover.html" "$DEVICE" || skip "the cover could not be written"
# A profile of its own: the owner may have the browser open, and a shared profile is locked.
# --password-store=basic: left to itself Chromium asks the desktop keyring for a key at
# start, and on a device that logs itself in the keyring is locked - so an unlock prompt
# flashed on the screen during the update until Chromium exited.
timeout 180 "$CHROMIUM" --headless=new --disable-gpu --allow-file-access-from-files \
    --password-store=basic \
    --no-pdf-header-footer --virtual-time-budget=5000 --user-data-dir="$WORK/profile" \
    --print-to-pdf="$WORK/cover.pdf" "file://$WORK/cover.html" > /dev/null 2>&1
[[ -s "$WORK/cover.pdf" && "$(qpdf --show-npages "$WORK/cover.pdf" 2> /dev/null)" == 1 ]] \
    || skip "chromium did not print a one-page cover"

# The shipped PDF stays the primary file so its named destinations - the index links -
# survive. qpdf exits 3 for warnings only.
qpdf "$SHARED_PDF" --pages "$WORK/cover.pdf" 1 "$SHARED_PDF" 2-z -- "$WORK/manual.pdf"
[[ $? -le 3 && -s "$WORK/manual.pdf" ]] || skip "qpdf could not put the cover on"

cp "$WORK/manual.pdf" "$OUT.tmp" && mv "$OUT.tmp" "$OUT" || skip "cannot write $OUT"
mkdir -p "$(dirname "$STAMP")"
echo "$WANT" > "$STAMP"
echo "Device manual written for $DEVICE: $OUT"
