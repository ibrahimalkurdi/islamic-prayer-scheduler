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

echo
[[ $fail -eq 0 ]] && echo "ALL PASS" || echo "FAILURES ABOVE"
exit $fail
