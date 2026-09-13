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

# A release cannot claim device data - but the pointer can, and says so. This is the
# sharp edge of the override, so it is asserted rather than left to the audio case.
echo "1.0.0" > "$SCH/var/installed_version"
point 1.1.0 '[]' '["config/config.ini"]'
before="$(md5sum "$SCH/config/config.ini" | cut -d' ' -f1)"
out="$(run)"
expect "pointer overrides the deny-list, loudly" "$out" "FORCED: config/config.ini"
# Forcing a path is only half of it: the release still has to carry the file. This one
# never does - make_release.sh strips it - so the force resolves to nothing.
expect "and a path no release ships is a no-op" "$out" "skipping config/config.ini - not in this release"
[ "$before" = "$(md5sum "$SCH/config/config.ini" | cut -d' ' -f1)" ] \
    && echo "  ✓ config.ini untouched" || { echo "  ✗ config.ini was modified"; fail=1; }

# The two paths the updater is itself writing to while it runs stay refused from either
# source. Not a matter of trust - copying over them corrupts the run doing the copying.
echo "1.0.0" > "$SCH/var/installed_version"
point 1.1.0 '[]' '["var/update/"]'
out="$(run)"
expect "the updater's own path is still refused" "$out" "which this update is"
chk_installed 1.0.0

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

echo "11. audio that ships with a release is seeded into the device's own folder"
conf PIN ""
conf APPLY_MODE ""
point 1.1.0
SEEDED="$SCH/audio/shorooq/sunrise.mp3"
LEDGER="$SCH/var/seeded-audio"

# A device that has never seen this release: no ledger, nothing in the folder.
rm -f "$SEEDED" "$LEDGER"
echo "1.0.0" > "$SCH/var/installed_version"
run > /dev/null
[ "$(cat "$SEEDED" 2>/dev/null)" = "FIXTURE-DEFAULT-SHOROOQ" ] \
    && echo "  ✓ the release's audio was copied into audio/shorooq/" \
    || { echo "  ✗ default audio was not seeded"; fail=1; }
grep -qxF "shorooq/sunrise.mp3" "$LEDGER" \
    && echo "  ✓ and recorded in the ledger" || { echo "  ✗ nothing was recorded"; fail=1; }

# The owner deletes it because they do not want it. The next night must not bring it back.
rm -f "$SEEDED"
echo "1.0.0" > "$SCH/var/installed_version"
run > /dev/null
[ ! -e "$SEEDED" ] \
    && echo "  ✓ a recitation the owner deleted stays deleted" \
    || { echo "  ✗ the deleted file came back"; fail=1; }

# Their own file under the same name is never replaced by the shipped one.
rm -f "$LEDGER"
echo "OWNERS-CHOICE" > "$SEEDED"
echo "1.0.0" > "$SCH/var/installed_version"
run > /dev/null
[ "$(cat "$SEEDED")" = "OWNERS-CHOICE" ] \
    && echo "  ✓ a file the owner put there is not overwritten" \
    || { echo "  ✗ the owner's file was overwritten"; fail=1; }
rm -f "$SEEDED" "$LEDGER"

echo "12. a forced include installs, and never deletes beside what it installs"
# No release ships a denied path - make_release.sh strips them all - so one is put into
# this release by hand. That is what a future release doing it deliberately looks like.
PACK="$REL/pi4-v1.1.0/scheduler-pi4-1.1.0.tar.gz"
cp "$PACK" /tmp/pack.bak
cp "$REL/pi4-v1.1.0/version.json" /tmp/m4.bak
WORK="$(mktemp -d)"
tar -xzf "$PACK" -C "$WORK"
mkdir -p "$WORK/audio/shorooq"
echo "FROM-RELEASE" > "$WORK/audio/shorooq/from-release.mp3"
tar -czf "$PACK" -C "$WORK" .
python3 - "$REL/pi4-v1.1.0/version.json" "$(sha256sum "$PACK" | cut -d' ' -f1)" <<'P'
import json, sys
m = json.load(open(sys.argv[1])); m["sha256"] = sys.argv[2]
json.dump(m, open(sys.argv[1], "w"), indent=2)
P

# "full" is the mode that carries --delete. Against a forced path it must not be applied:
# the owner's own recitation is in that folder and is not in the payload.
conf APPLY_MODE full
echo "1.0.0" > "$SCH/var/installed_version"
point 1.1.0 '[]' '["audio/shorooq/"]'
out="$(run)"
expect "the forced path is named in the log" "$out" "FORCED: audio/shorooq/"
expect "and --delete is not applied to it"   "$out" "--delete not applied"
[ "$(cat "$SCH/audio/shorooq/from-release.mp3" 2>/dev/null)" = "FROM-RELEASE" ] \
    && echo "  ✓ the forced path was installed over the deny-list" \
    || { echo "  ✗ the forced path was not installed"; fail=1; }
[ "$(cat "$SCH/audio/shorooq/owners-own.mp3" 2>/dev/null)" = "FIXTURE-OWNERS-OWN" ] \
    && echo "  ✓ the owner's own recitation survived --delete" \
    || { echo "  ✗ the owner's audio was deleted"; fail=1; }
[ "$(cat "$SCH/audio/fajr/athan.mp3" 2>/dev/null)" = "FIXTURE-AUDIO" ] \
    && echo "  ✓ audio the pointer did not claim is untouched" \
    || { echo "  ✗ an unclaimed audio folder was touched"; fail=1; }

rm -rf "$WORK"
cp /tmp/pack.bak "$PACK"
cp /tmp/m4.bak "$REL/pi4-v1.1.0/version.json"
conf APPLY_MODE ""
point 1.1.0

echo "13. a device can follow a version file of its own"
# The failure mode this guards is silence: a device left on a test pointer takes versions
# nobody rolled out and misses the ones everybody got, with nothing on screen to say so.
printf '{\n  "pi4": {"version": "1.0.0", "exclude": [], "include": []},\n  "zero": ""\n}\n' \
    > "$REL/VERSIONS-test.json"
point 1.1.0
echo "1.1.0" > "$SCH/var/installed_version"
conf UPDATE_POINTER_URL "\"file://$REL/VERSIONS-test.json\""
out="$(run)"
expect "the custom file decides the version" "$out" "Target 1.0.0 (version pointer)"
expect "and the device says which file it follows" "$out" "Version pointer: VERSIONS-test.json"
expect "--status names it too" "$(run --status)" '"pointer": "VERSIONS-test.json"'
# Cleared means "follow the fleet's file" - which for this fixture is the local one it
# started with, not raw.githubusercontent.com.
conf UPDATE_POINTER_URL "\"file://$REL/VERSIONS.json\""
out="$(run --status)"
grep -qF '"pointer_is_default": true' <<< "$out" \
    && echo "  ✓ clearing it puts the device back on the fleet's file" \
    || { echo "  ✗ still following the custom pointer"; fail=1; }
grep -qF "NOT the default" <<< "$(run)" \
    && { echo "  ✗ still warning after being cleared"; fail=1; } \
    || echo "  ✓ and the warning stops"
rm -f "$REL/VERSIONS-test.json"

echo "16. when the primary host is unreachable the mirror carries the update"
# Syria blocks every GitHub host this script fetches from - the raw pointer, the release
# assets, the API - so a device there reads nothing at all and never even learns a
# version exists. Codeberg carries the same repo and the same releases behind it. Here
# the primary is pointed at a directory that is not there, which is what a blocked host
# looks like to curl: no answer, whatever the reason.
SAVED_CONF="$(cat "$SCH/config/update.conf")"
mirror_conf() { # $1 primary base, $2 mirror base
    cat >> "$SCH/config/update.conf" <<CONF
UPDATE_POINTER_URL="file://$1/VERSIONS.json"
UPDATE_POINTER_MIRROR="file://$2/VERSIONS.json"
UPDATE_DOWNLOAD_URL="file://$1"
UPDATE_DOWNLOAD_MIRROR="file://$2"
CONF
}

point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
mirror_conf "$REL/blocked" "$REL"
out="$(run --now)"
expect "the dead primary is reported, not swallowed" "$out" "no answer from"
expect "and the mirror is named as the one that answered" "$out" "served by the mirror instead"
expect "the update goes through anyway" "$out" "==== Updated to 1.1.0 ===="
chk_installed="$(cat "$SCH/var/installed_version")"
[ "$chk_installed" = "1.1.0" ] \
    && echo "  ✓ and the device is really on the new version" \
    || { echo "  ✗ installed_version says $chk_installed"; fail=1; }

echo "17. with both hosts unreachable it fails where it stands"
# The mirror must not turn a total outage into a half-finished install: nothing has been
# downloaded, so nothing should have been touched.
echo "1.1.0" > "$SCH/var/installed_version"
point 1.1.1
echo "$SAVED_CONF" > "$SCH/config/update.conf"
mirror_conf "$REL/blocked" "$REL/also-blocked"
out="$(run --now)"
expect "both hosts are named" "$out" "no answer from"
expect "and it stops at the pointer rather than guessing" "$out" "Cannot read the version pointer"
still="$(cat "$SCH/var/installed_version")"
[ "$still" = "1.1.0" ] \
    && echo "  ✓ the device is left on the version it had" \
    || { echo "  ✗ installed_version moved to $still"; fail=1; }

echo "18. a device pointed at one host by hand is not sent anywhere else"
# Naming a host in update.conf is an instruction. Reaching past it to the built-in
# mirror would ignore that - and would put a test rig on the real network.
echo "$SAVED_CONF" > "$SCH/config/update.conf"
conf UPDATE_POINTER_URL "\"file://$REL/blocked/VERSIONS.json\""
out="$(run --now)"
expect "the named host is tried" "$out" "no answer from"
grep -qF "served by the mirror instead" <<< "$out" \
    && { echo "  ✗ it fell through to a mirror nobody asked for"; fail=1; } \
    || echo "  ✓ and nothing is tried behind it"

echo "$SAVED_CONF" > "$SCH/config/update.conf"

echo
[ $fail -eq 0 ] && echo "ALL PASS" || echo "FAILURES ABOVE"
