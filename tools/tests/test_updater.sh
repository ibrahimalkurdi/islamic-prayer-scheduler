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

echo "19. an empty POINTER_NAME still means VERSIONS.json"
# update.conf ships the key empty to mean "the default", and the default used to be
# applied before the file was sourced - so the empty value won and the pointer URL came
# out as .../main/ with no file name on the end. Every device installed since 1.1.0 was
# frozen there, on every host, mirror included. --status resolves the pointer and exits
# before any fetch, which is the whole of what this needs to see.
grep -v '^UPDATE_POINTER_URL=' <<< "$SAVED_CONF" > "$SCH/config/update.conf"
echo 'POINTER_NAME=' >> "$SCH/config/update.conf"
out="$(run --status)"
expect "the default file name is restored" "$out" '"pointer": "VERSIONS.json"'
expect "and the device still counts as following the fleet" "$out" '"pointer_is_default": true'

echo "20. and it really updates through the default pointer"
# The gap that let 19 ship: every other case here names UPDATE_POINTER_URL, which takes
# the other branch and recovers the name with basename, so the built-in host was never
# once exercised. This leaves it unset and points the host itself at the fixture.
run_default_host() { HOME="$DEV" DEVICE_MODEL_FILE="$HERE/fake_model" HEALTH_SETTLE_SECONDS=1 \
        POINTER_REPO_RAW="file://$REL" POINTER_REPO_MIRROR="file://$REL/blocked" \
        timeout 120 bash "$CU" "$@" 2>&1; }
point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_default_host --now)"
expect "the pointer is read from the built-in host" "$out" "==== Updated to 1.1.0 ===="
chk_installed="$(cat "$SCH/var/installed_version")"
[ "$chk_installed" = "1.1.0" ] \
    && echo "  ✓ and the device is really on the new version" \
    || { echo "  ✗ installed_version says $chk_installed"; fail=1; }

echo "21. an update restarts the website as well as the athan service"
# Case 19 stripped UPDATE_POINTER_URL to exercise the built-in host, and 20 pointed that
# host at the fixture. Without putting the original conf back, this would try the real
# GitHub, fail to read a pointer, and never reach the restart step at all - passing for
# the wrong reason or failing for one.
echo "$SAVED_CONF" > "$SCH/config/update.conf"
# The website holds the previous version's Python until it is restarted, so a release
# that changes it would be installed and not running. Neither systemctl nor sudo can do
# anything useful in a fixture, so both are stubbed onto PATH and asked only what was
# called - which is the whole of what this needs to prove.
STUB="$HERE/stub-bin"
mkdir -p "$STUB"
CALLED="$HERE/systemctl-calls"
: > "$CALLED"
cat > "$STUB/systemctl" <<STUBEOF
#!/bin/bash
echo "systemctl \$*" >> "$CALLED"
# The website's unit counts as installed and enabled; everything else is answered the
# way the real one answers for a unit that is running.
case "\$*" in
    "list-unit-files scheduler_web_ui.service") exit 0 ;;
    "is-enabled --quiet scheduler_web_ui.service") exit 0 ;;
esac
exit 0
STUBEOF
cat > "$STUB/sudo" <<'STUBEOF'
#!/bin/bash
# Drop -n and any other flag, then run the real command - which here is the stub above.
while [[ "$1" == -* ]]; do shift; done
exec "$@"
STUBEOF
chmod +x "$STUB/systemctl" "$STUB/sudo"

run_stubbed() { HOME="$DEV" DEVICE_MODEL_FILE="$HERE/fake_model" HEALTH_SETTLE_SECONDS=1 \
        PATH="$STUB:$PATH" timeout 120 bash "$CU" "$@" 2>&1; }
point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
expect "the athan service is restarted" "$(cat "$CALLED")" "systemctl restart audio_event_scheduler.service"
expect "and so is the website" "$(cat "$CALLED")" "systemctl restart scheduler_web_ui.service"

echo "22. but not on a device where the website was never installed"
: > "$CALLED"
cat > "$STUB/systemctl" <<STUBEOF
#!/bin/bash
echo "systemctl \$*" >> "$CALLED"
# No such unit - a device that has not run init.sh since the website arrived.
case "\$*" in
    "list-unit-files scheduler_web_ui.service") exit 1 ;;
    "is-enabled --quiet scheduler_web_ui.service") exit 1 ;;
esac
exit 0
STUBEOF
chmod +x "$STUB/systemctl"
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
expect "the athan service is still restarted" "$(cat "$CALLED")" "systemctl restart audio_event_scheduler.service"
if grep -qF "systemctl restart scheduler_web_ui.service" "$CALLED"; then
    echo "  ✗ the website was restarted on a device that has no such unit"; fail=1
else
    echo "  ✓ the website is left alone, and reported rather than warned about"
fi
rm -rf "$STUB" "$CALLED"

echo "$SAVED_CONF" > "$SCH/config/update.conf"

echo "23. an update applies the root work a release brings, without anyone present"
# Units, icons and packages all need root, and 02:00 has nobody to type a password. The
# updater asks the NOPASSWD helper whether there is anything to do and runs it if so.
STUB="$HERE/stub-bin"
mkdir -p "$STUB"
APPLIED="$HERE/apply-calls"
: > "$APPLIED"
mkdir -p "$STUB/usr/local/sbin"
cat > "$STUB/sudo" <<STUBEOF
#!/bin/bash
while [[ "\$1" == -* ]]; do shift; done
if [[ "\$1" == "/usr/local/sbin/scheduler-apply-system" ]]; then
    shift
    echo "apply \$*" >> "$APPLIED"
    # --check answers "yes, there is work", the way a release with a new unit would.
    [[ "\${1:-}" == "--check" ]] && exit 10
    exit 0
fi
exec "\$@"
STUBEOF
cat > "$STUB/systemctl" <<'STUBEOF'
#!/bin/bash
exit 0
STUBEOF
chmod +x "$STUB/sudo" "$STUB/systemctl"
point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
expect "it asks whether there is root work to do" "$(cat "$APPLIED")" "apply --check"
if grep -qx "apply " "$APPLIED"; then
    echo "  ✓ and runs it when the answer is yes"
else
    echo "  ✗ it never ran the helper after being told there was work"; fail=1
fi
expect "and says so in the log" "$out" "Applying the system changes"

echo "24. a device without the helper is told, not broken"
# Every device in the field predates this. There the sudo call fails outright, which must
# read as "cannot be asked" - the old report - and never as "nothing to do".
: > "$APPLIED"
cat > "$STUB/sudo" <<'STUBEOF'
#!/bin/bash
while [[ "$1" == -* ]]; do shift; done
# sudo's own exit code when no rule matches the command.
[[ "$1" == "/usr/local/sbin/scheduler-apply-system" ]] && exit 1
exec "$@"
STUBEOF
chmod +x "$STUB/sudo"
point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
expect "it falls back to reporting the unit" "$out" "run init.sh to install it"
if grep -q "Applying the system changes" <<< "$out"; then
    echo "  ✗ it tried to apply anyway after sudo refused"; fail=1
else
    echo "  ✓ and does not pretend the work was done"
fi
rm -rf "$STUB" "$APPLIED"

echo "25. a release can ask for setup to be run, and it happens with nobody present"
# Not everything a release changes is a file or a unit. A new desktop shortcut, a cron
# entry, a font - those live in init.sh. A release asks for it by shipping
# config/needs_init, and the stamp in var/ is what keeps it to once per release rather
# than every night.
STUB="$HERE/stub-bin"
mkdir -p "$STUB"
cat > "$STUB/sudo" <<'STUBEOF'
#!/bin/bash
while [[ "$1" == -* ]]; do shift; done
# The helper answers, and nothing else does. That is the real shape of an update at
# 02:00: cron has no terminal, so sudo -n true fails, init.sh sets CAN_PROMPT=0, and
# every root command outside the helper is skipped and reported. Passing other commands
# through instead would have this test running mkdir and install against /usr/local on
# whatever machine it is on.
[[ "$1" == "/usr/local/sbin/scheduler-apply-system" ]] && exit 0
exit 1
STUBEOF
# This machine is not a Raspberry Pi. The real init.sh runs here, which is the point -
# what is under test is the updater starting it for real - but everything it shells out
# to that would touch this machine is stubbed away.
for tool in crontab hostnamectl systemctl fc-cache gtk-update-icon-cache unzip \
            xdotool dpkg apt-get gsettings; do
    printf '#!/bin/bash\nexit 0\n' > "$STUB/$tool"
done
chmod +x "$STUB"/*
# Rebuilding the prayer map would need pandas, which is nothing to do with this.
mkdir -p "$SCH/var/setup_done"
touch "$SCH/var/setup_done/settings_applied"

# Not written into the live tree: the updater rsyncs config/ and anything not in the
# release payload is deleted, which is right - a release asks for setup by *shipping*
# this file, so it has to arrive with the release. The fixture builds its releases from
# the repo, so the file under test is the real one.
rm -f "$SCH/var/init_ran_for"
point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
LOG="$SCH/logs/check_updates.log"

expect "it says the release asked for setup" "$out" "This release asks for setup to be run"
expect "and setup really ran" "$(cat "$LOG")" "Scheduler setup started"
# The one that would bite: the last thing init.sh does is check for updates, so being
# started by the updater is exactly when it must not.
expect "without the two calling each other for ever" \
    "$(cat "$LOG")" "Started by the updater"
# Taken from the log rather than from config/, because the release's copy is what the
# updater reads and a device is not guaranteed to have one - the manifest's include list
# names the config/ entries a release may replace, and this is not among them.
want="$(sed -n 's/.*asks for setup to be run (\([^)]*\)).*/\1/p' <<< "$out" | head -n 1)"
if [[ -n "$want" && "$(head -n 1 "$SCH/var/init_ran_for" 2>/dev/null)" == "$want" ]]; then
    echo "  ✓ and the device records what it ran setup for"
else
    echo "  ✗ no stamp written, so it would run setup again every night"; fail=1
fi

# Same release, same ask, a device that has already done it.
echo "1.0.0" > "$SCH/var/installed_version"
point 1.1.0
out="$(run_stubbed --now)"
if grep -q "This release asks for setup to be run" <<< "$out"; then
    echo "  ✗ it ran setup again for a release it had already run it for"; fail=1
else
    echo "  ✓ a release that already had its setup run does not get it twice"
fi

rm -f "$SCH/var/init_ran_for"
rm -rf "$STUB"

echo "26. a release can bring steps of its own, and is rolled back if they fail"
# Neither hook is shipped. A release that needs a step the updater has no concept of -
# a directory made, something renamed, a file moved before the new one lands - adds the
# one it needs and it runs; a release that adds nothing gets nothing.
rm -f "$SCH/var/pre_update_ran" "$SCH/var/post_update_ran" \
      "$SCH/var/fail_pre_update" "$SCH/var/fail_post_update"
point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
expect "the release's pre_update.sh runs" "$out" "Running this release's pre_update.sh"
expect "and its post_update.sh too" "$out" "Running this release's post_update.sh"
if [[ -f "$SCH/var/pre_update_ran" && -f "$SCH/var/post_update_ran" ]]; then
    echo "  ✓ both really ran, not just logged"
else
    echo "  ✗ a hook was announced but left no trace"; fail=1
fi
# The order is the whole point of there being two: pre runs while the old version is
# still in place, post once the new files are down.
pre_line="$(grep -n "pre_update.sh" <<< "$out" | head -n 1 | cut -d: -f1)"
inst_line="$(grep -n "Installing 1.1.0" <<< "$out" | head -n 1 | cut -d: -f1)"
post_line="$(grep -n "post_update.sh" <<< "$out" | head -n 1 | cut -d: -f1)"
if [[ -n "$pre_line" && -n "$inst_line" && -n "$post_line" \
      && $pre_line -lt $inst_line && $post_line -gt $inst_line ]]; then
    echo "  ✓ pre runs before the install, post after it"
else
    echo "  ✗ hooks ran in the wrong order ($pre_line/$inst_line/$post_line)"; fail=1
fi

# A release whose own steps fail is a release that did not work, and the device must end
# up where it started rather than half way.
touch "$SCH/var/fail_post_update"
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
expect "a failing post_update.sh is reported" "$out" "post_update.sh failed"
expect "and the old version is put back" "$out" "putting 1.0.0 back"
if [[ "$(cat "$SCH/var/installed_version")" == "1.0.0" ]]; then
    echo "  ✓ the device is left on the version it started from"
else
    echo "  ✗ it recorded the update anyway"; fail=1
fi
rm -f "$SCH/var/fail_post_update"

# pre fails before anything has been touched, so there is nothing to restore.
touch "$SCH/var/fail_pre_update"
echo "1.0.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
expect "a failing pre_update.sh stops the update" "$out" "pre_update.sh failed"
if grep -q "Installing 1.1.0" <<< "$out"; then
    echo "  ✗ it installed anyway after the pre step failed"; fail=1
else
    echo "  ✓ and nothing was installed"
fi
rm -f "$SCH/var/fail_pre_update" "$SCH/var/pre_update_ran" "$SCH/var/post_update_ran"

# 1.0.0 carries neither, which is the normal case and must be silent.
point 1.0.0
echo "1.1.0" > "$SCH/var/installed_version"
out="$(run_stubbed --now)"
if grep -q "_update.sh" <<< "$out"; then
    echo "  ✗ it announced a hook a release does not ship"; fail=1
else
    echo "  ✓ a release that brings no steps of its own says nothing"
fi

# Put the device back where this section found it. The check above has to leave it on
# 1.0.0 to prove the quiet case, and this suite - and the ones run after it - start from
# a device on the newest release.
point 1.1.0
echo "1.0.0" > "$SCH/var/installed_version"
run_stubbed --now > /dev/null 2>&1
rm -f "$SCH/var/pre_update_ran" "$SCH/var/post_update_ran"

echo
[ $fail -eq 0 ] && echo "ALL PASS" || echo "FAILURES ABOVE"
