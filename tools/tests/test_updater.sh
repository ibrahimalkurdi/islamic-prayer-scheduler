#!/bin/bash
# Exercise every refusal and recovery path of check_updates.sh.
HERE="$(cd "$(dirname "$0")" && pwd)"
DEV="$HERE/dev"; SCH="$DEV/Desktop/scheduler"; REL="$HERE/releases"
CU="$SCH/config/scripts/check_updates.sh"
fail=0
echo "Raspberry Pi 4 Model B Rev 1.5" > "$HERE/fake_model"
run() { HOME="$DEV" DEVICE_MODEL_FILE="$HERE/fake_model" HEALTH_SETTLE_SECONDS=1 \
        timeout 120 bash "$CU" "$@" 2>&1; }
expect() { # name, haystack, needle
    if grep -qF -- "$3" <<< "$2"; then echo "  ✓ $1"; else echo "  ✗ $1"; echo "$2" | tail -4 | sed 's/^/       /'; fail=1; fi
}
conf() { python3 - "$SCH/config/update.conf" "$1" "$2" <<'P'
import re, sys
path, key, value = sys.argv[1:4]
text = open(path).read()
text = re.sub(rf"^{key}=.*$", f"{key}={value}", text, flags=re.M)
open(path, "w").write(text)
P
}
point() { # $1 version, $2 exclude JSON array, $3 include JSON array
    printf '{\n  "pi4": {"version": "%s", "exclude": %s, "include": %s},\n  "zero": ""\n}\n' \
        "$1" "${2:-[]}" "${3:-[]}" > "$REL/VERSIONS.json"
}
point_plain() { printf '{\n  "pi4": "%s",\n  "zero": ""\n}\n' "$1" > "$REL/VERSIONS.json"; }

# Start from a known device state. Without this the suite inherits whatever an earlier
# run - or the Settings test, which pins on purpose - left in update.conf, and a pin
# quietly turns every "update now" into "already on that version".
echo "1.0.0" > "$SCH/var/installed_version"
conf PIN ""
conf ENABLED true
conf EXTRA_EXCLUDE ""
conf VARIANT pi4

echo "1. a release for the other variant is refused before download"
python3 - "$REL/pi4-v1.1.0/version.json" <<'P'
import json, sys
m = json.load(open(sys.argv[1])); m["variant"] = "zero"
json.dump(m, open(sys.argv[1], "w"), indent=2)
P
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run --now)"
expect "refused, names both variants" "$out" "this release is for 'zero', this device is 'pi4'"
expect "nothing was downloaded" "$out" "refusing before download"
python3 - "$REL/pi4-v1.1.0/version.json" <<'P'
import json, sys
m = json.load(open(sys.argv[1])); m["variant"] = "pi4"
json.dump(m, open(sys.argv[1], "w"), indent=2)
P

echo "2. update.conf disagreeing with the hardware"
conf VARIANT zero
out="$(run --now)"
expect "conf-vs-hardware mismatch caught" "$out" "Refusing to update"
conf VARIANT pi4

echo "3. ENABLED=false"
conf ENABLED false
out="$(run)"
expect "cron run does nothing"   "$out" "Updates are disabled"
out="$(run --now)"
expect "--now still works"       "$out" "Updating"
conf ENABLED true

echo "4. a manifest naming protected data is refused outright"
cp "$REL/pi4-v1.1.0/version.json" /tmp/m.bak
python3 - "$REL/pi4-v1.1.0/version.json" <<'P'
import json, sys
m = json.load(open(sys.argv[1])); m["include"].append("config/config.ini")
json.dump(m, open(sys.argv[1], "w"), indent=2)
P
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run --now)"
expect "protected path refused" "$out" "which is device data"
cp /tmp/m.bak "$REL/pi4-v1.1.0/version.json"

echo "5. a torn download is refused and nothing is touched"
cp "$REL/pi4-v1.1.0/scheduler-pi4-1.1.0.tar.gz" /tmp/a.bak
head -c 2000 /tmp/a.bak > "$REL/pi4-v1.1.0/scheduler-pi4-1.1.0.tar.gz"
before="$(md5sum "$SCH/applications/desktop/prayer_times_gui/main.py" | cut -d' ' -f1)"
out="$(run --now)"
expect "checksum mismatch caught" "$out" "checksum mismatch"
after="$(md5sum "$SCH/applications/desktop/prayer_times_gui/main.py" | cut -d' ' -f1)"
[ "$before" = "$after" ] && echo "  ✓ live tree untouched" || { echo "  ✗ live tree changed"; fail=1; }
cp /tmp/a.bak "$REL/pi4-v1.1.0/scheduler-pi4-1.1.0.tar.gz"

echo "6. EXTRA_EXCLUDE protects a locally edited file"
echo "# LOCAL EDIT" >> "$SCH/config/pipewire-pulse.conf"
conf EXTRA_EXCLUDE '"config/pipewire-pulse.conf"'
echo "1.0.0" > "$SCH/var/installed_version"
run --now > /dev/null
grep -q "LOCAL EDIT" "$SCH/config/pipewire-pulse.conf" \
    && echo "  ✓ local edit survived" || { echo "  ✗ local edit was overwritten"; fail=1; }
conf EXTRA_EXCLUDE ""

echo "7. the version pointer decides what an unpinned device installs"
point 1.1.0
out="$(run)"
expect "an unpinned device follows the pointer" "$out" "Target 1.1.0 (version pointer)"

# The fleet rollback: one edit, and every unpinned device walks back on its next check.
point 1.0.0
out="$(run)"
expect "moving the pointer back downgrades the device" "$out" "Target 1.0.0 (version pointer)"
expect "and it actually installed" "$out" "Health check passed"
chk_installed() { [ "$(cat "$SCH/var/installed_version")" = "$1" ] \
    && echo "  ✓ installed_version is $1" || { echo "  ✗ installed_version is $(cat "$SCH/var/installed_version"), wanted $1"; fail=1; }; }
chk_installed 1.0.0

# A pointer we cannot read is not the same as a pointer saying "stay put" - treating it
# as "nothing to do" would be fine, but treating it as "no release, fall back to newest"
# would quietly undo a fleet rollback during a network blip.
mv "$REL/VERSIONS.json" "$REL/VERSIONS.json.away"
out="$(run)"
expect "an unreachable pointer stops the run" "$out" "Cannot read the version pointer"
chk_installed 1.0.0
mv "$REL/VERSIONS.json.away" "$REL/VERSIONS.json"

point ""
out="$(run)"
expect "a pointer naming no version installs nothing" "$out" "names no version for variant"
point 1.1.0

echo "8. the pointer's per-variant path rules"
# A path the release ships and this hardware wants to keep - the fleet-wide EXTRA_EXCLUDE.
echo "1.0.0" > "$SCH/var/installed_version"
run --target 1.0.0 > /dev/null 2>&1
echo "# FLEET LOCAL EDIT" >> "$SCH/config/pipewire-pulse.conf"
point 1.1.0 '["config/pipewire-pulse.conf"]'
out="$(run)"
expect "pointer exclude keeps the file" "$out" "excluded by the version pointer"
grep -q "FLEET LOCAL EDIT" "$SCH/config/pipewire-pulse.conf" \
    && echo "  ✓ the excluded file was not replaced" || { echo "  ✗ excluded file was overwritten"; fail=1; }
chk_installed 1.1.0

# A path the release ships but its manifest does not name - the case where one hardware
# needs something the packager's default list leaves out. Claiming it centrally has to
# reach the device without a new release being cut.
cp "$REL/pi4-v1.1.0/version.json" /tmp/m2.bak
python3 - "$REL/pi4-v1.1.0/version.json" <<'P'
import json, sys
m = json.load(open(sys.argv[1]))
m["include"] = [p for p in m["include"] if p != "config/icons/"]
json.dump(m, open(sys.argv[1], "w"), indent=2)
P
echo "1.0.0" > "$SCH/var/installed_version"
rm -rf "$SCH/config/icons"
point 1.1.0 '[]' '["config/icons/"]'
out="$(run)"
expect "pointer include is added" "$out" "adding config/icons/ (named by the version pointer)"
[ -d "$SCH/config/icons" ] && [ -n "$(ls -A "$SCH/config/icons" 2>/dev/null)" ] \
    && echo "  ✓ the added path was installed" || { echo "  ✗ added path never arrived"; fail=1; }
cp /tmp/m2.bak "$REL/pi4-v1.1.0/version.json"

# An empty include/exclude in the object form must add nothing. It used to add one empty
# string, which resolved to the staging root and rsynced the whole tree over the device -
# quietly replacing paths the release never claimed. Proven by a path the release ships
# and the manifest does NOT name: it must stay absent.
cp "$REL/pi4-v1.1.0/version.json" /tmp/m3.bak
python3 - "$REL/pi4-v1.1.0/version.json" <<'P'
import json, sys
m = json.load(open(sys.argv[1]))
m["include"] = [p for p in m["include"] if p != "config/icons/"]
json.dump(m, open(sys.argv[1], "w"), indent=2)
P
echo "1.0.0" > "$SCH/var/installed_version"
rm -rf "$SCH/config/icons"
point 1.1.0 '[]' '[]'
out="$(run)"
grep -q "adding  (named by the version pointer)" <<< "$out" \
    && { echo "  ✗ an empty path was added"; fail=1; } || echo "  ✓ an empty include adds nothing"
[ ! -d "$SCH/config/icons" ] \
    && echo "  ✓ an unnamed path was not copied" || { echo "  ✗ the whole staging tree was rsynced"; fail=1; }
chk_installed 1.1.0
cp /tmp/m3.bak "$REL/pi4-v1.1.0/version.json"

# Central does not mean trusted: the pointer faces the same refusal a manifest does.
echo "1.0.0" > "$SCH/var/installed_version"
point 1.1.0 '[]' '["config/config.ini"]'
before="$(md5sum "$SCH/config/config.ini" | cut -d' ' -f1)"
out="$(run)"
expect "pointer naming protected data is refused" "$out" "the version pointer asks to replace 'config/config.ini'"
[ "$before" = "$(md5sum "$SCH/config/config.ini" | cut -d' ' -f1)" ] \
    && echo "  ✓ config.ini untouched" || { echo "  ✗ config.ini was modified"; fail=1; }

# The shorthand form has to keep working - it is what most variants will use.
point_plain 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run)"
expect "the plain string form still resolves" "$out" "Target 1.1.0 (version pointer)"
point 1.1.0

echo "9. a pin overrides the pointer"
conf PIN 1.0.0
out="$(run)"
expect "pin wins over the pointer" "$out" "Target 1.0.0 (pinned in update.conf)"
conf PIN ""

echo "10. rollback restores the retained version"
out="$(run --rollback)"
expect "rolled back" "$out" "Rolling back to"
echo
[ $fail -eq 0 ] && echo "ALL PASS" || echo "FAILURES ABOVE"
