#!/bin/bash
# config/scripts/device_manual.sh: a device puts a cover of its own in front of the shipped
# manual. Runs on a copy of the tree, so the repo and the real Desktop are never touched.
# Needs google-chrome (or chromium), qpdf and pdftotext; segno comes from the venv
# build_manual_pdf.sh makes.
#
#   bash tools/tests/test_device_manual.sh
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TREE="$REPO_ROOT/scheduler-official-touch-screen-with-raspberry-pi-4"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail=0
chk() { if [ "$2" = "$3" ]; then echo "  ✓ $1"; else echo "  ✗ $1 — expected $3, got $2"; fail=1; fi; }

PYTHON="$REPO_ROOT/tools/manual_pdf/.venv/bin/python"
[ -x "$PYTHON" ] || { echo "run tools/build_manual_pdf.sh once first, for its venv"; exit 1; }
CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser)"

SCHED="$WORK/home/Desktop/scheduler"
mkdir -p "$SCHED/applications" "$SCHED/config/icons" "$SCHED/config/scripts"
cp -r "$TREE/applications/manual_cover" "$SCHED/applications/"
cp "$TREE/config/icons/athan-app-icon-256.png" "$SCHED/config/icons/"
cp "$TREE/config/scripts/device_manual.sh" "$SCHED/config/scripts/"
cp "$TREE/USER_MANUAL_AR.pdf" "$SCHED/"
OUT="$WORK/home/Desktop/دليل-المستخدم.pdf"

run() { # $1 hostname, rest: extra environment
    local host="$1"; shift
    env HOME="$WORK/home" DEVICE_MANUAL_HOST="$host" CHROMIUM="$CHROME" MANUAL_PYTHON="$PYTHON" "$@" \
        bash "$SCHED/config/scripts/device_manual.sh"
}
cover_text() { pdftotext -f 1 -l 1 "$OUT" - 2> /dev/null | tr -d '\n'; }

echo "1. the device's own copy"
run ihms-lr > "$WORK/log" 2>&1
chk "it says it wrote it" "$(grep -c "written for ihms-lr" "$WORK/log")" "1"
chk "on the Desktop" "$([ -s "$OUT" ] && echo yes)" "yes"
chk "same page count as the shipped manual" "$(qpdf --show-npages "$OUT")" \
    "$(qpdf --show-npages "$SCHED/USER_MANUAL_AR.pdf")"
chk "the cover names this device" "$(cover_text | grep -c "http://ihms-lr.local")" "1"
chk "and not the placeholder" "$(cover_text | grep -c "hostname.local")" "0"
chk "the pages behind it are the shipped ones" \
    "$(pdftotext -f 2 -l 8 "$OUT" - | md5sum)" "$(pdftotext -f 2 -l 8 "$SCHED/USER_MANUAL_AR.pdf" - | md5sum)"
chk "the index links survive" "$(pdfinfo -dests "$OUT" | wc -l)" "$(pdfinfo -dests "$SCHED/USER_MANUAL_AR.pdf" | wc -l)"

echo "2. remade only when something changed"
before="$(stat -c %Y.%s "$OUT")"
run ihms-lr > "$WORK/log" 2>&1
chk "a second run leaves it alone" "$(grep -c "already up to date" "$WORK/log")" "1"
chk "the file is untouched" "$(stat -c %Y.%s "$OUT")" "$before"
run louay > "$WORK/log" 2>&1
chk "a new hostname remakes it" "$(cover_text | grep -c "http://louay.local")" "1"
echo " " >> "$SCHED/USER_MANUAL_AR.pdf"
run louay > "$WORK/log" 2>&1
chk "a new shipped manual remakes it" "$(grep -c "written for louay" "$WORK/log")" "1"
rm "$OUT"
run louay > "$WORK/log" 2>&1
chk "a deleted copy comes back" "$([ -s "$OUT" ] && echo yes)" "yes"

echo "3. the name Avahi advertises wins over the hostname"
printf '[server]\n#host-name=commented\nhost-name=ihms-lr\nuse-ipv4=yes\n' > "$WORK/avahi.conf"
env HOME="$WORK/home" AVAHI_CONF="$WORK/avahi.conf" CHROMIUM="$CHROME" MANUAL_PYTHON="$PYTHON" \
    bash "$SCHED/config/scripts/device_manual.sh" > "$WORK/log" 2>&1
chk "Avahi's own name is on the cover" "$(cover_text | grep -c "http://ihms-lr.local")" "1"
env HOME="$WORK/home" AVAHI_CONF="$WORK/none.conf" CHROMIUM="$CHROME" MANUAL_PYTHON="$PYTHON" \
    bash "$SCHED/config/scripts/device_manual.sh" > "$WORK/log" 2>&1
chk "without one, the hostname" "$(cover_text | grep -c "http://$(hostname).local")" "1"

echo "4. never fatal"
rm "$OUT"
run louay CHROMIUM=/nonexistent > "$WORK/log" 2>&1
chk "a chromium that prints nothing is skipped, exit 0" "$?" "0"
chk "and says so" "$(grep -c "skipped" "$WORK/log")" "1"
chk "and leaves nothing half-made" "$(ls "$WORK/home/Desktop" | grep -c pdf)" "0"
run louay MANUAL_PYTHON=/usr/bin/false > "$WORK/log" 2>&1
chk "no segno is skipped, exit 0" "$?" "0"
run "bad name" > "$WORK/log" 2>&1
chk "a hostname that is no .local name is skipped" "$(grep -c "cannot be a .local name" "$WORK/log")" "1"
mv "$SCHED/applications/manual_cover/cover.json" "$WORK/"
run louay > "$WORK/log" 2>&1
chk "a tree without the cover data is skipped, exit 0" "$?" "0"

echo "5. no keyring prompt on the screen"
mv "$WORK/cover.json" "$SCHED/applications/manual_cover/"
cat > "$WORK/fake-chromium" <<STUB
#!/bin/bash
echo "\$@" > "$WORK/chromium-args"
STUB
chmod +x "$WORK/fake-chromium"
rm -f "$OUT"
run louay CHROMIUM="$WORK/fake-chromium" > "$WORK/log" 2>&1
chk "chromium keeps away from the desktop keyring" \
    "$(grep -c -- "--password-store=basic" "$WORK/chromium-args")" "1"

echo
[ "$fail" -eq 0 ] && echo "all passed" || { echo "FAILED"; exit 1; }
