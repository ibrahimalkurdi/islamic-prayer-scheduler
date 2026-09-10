#!/bin/bash
# Build a throwaway device + release server, so the updater can be exercised end to end
# without a Raspberry Pi and without publishing anything.
#
#   tools/tests/make_fixture.sh [fixture_dir]     default /tmp/scheduler-update-test
#
# What it makes, under the fixture directory:
#
#   dev/Desktop/scheduler   a device tree - real code, plus the state an update must not
#                           touch: a config.ini with a recognisable setting, the generated
#                           prayer map, and a stand-in audio file
#   releases/               two published pi4 releases (1.0.0 and 1.1.0), an index.json,
#                           and the VERSIONS.json pointer that decides what installs,
#                           read over file:// - curl handles that, so no server is needed
#   test_updater.sh         the four test scripts, copied in beside them - each finds
#   test_state_survives.sh    the fixture from its own directory, so they run from here
#   test_settings_updates.py
#   test_friday_quran.py
#
# health_check.sh is replaced by a stub in both the device tree and the releases. It is
# the one thing that cannot be faked off-device: it asks systemd whether the athan
# service is up and X whether the countdown has a window, and neither exists here. The
# stub is what makes the update path testable; every other script is the real one.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE="${1:-/tmp/scheduler-update-test}"
SUBTREE="scheduler-official-touch-screen-with-raspberry-pi-4"
TREE="$REPO_ROOT/$SUBTREE"

RELEASES="$FIXTURE/releases"
DEV="$FIXTURE/dev"
SCHEDULER="$DEV/Desktop/scheduler"
BUILD="$FIXTURE/build-repo"

HEALTH_STUB='#!/bin/bash
# TEST SCAFFOLD - stands in for the real checks where there is no systemd or X server.
echo "  OK    (stub health check)"
exit 0
'

echo "==> Fixture at $FIXTURE"
rm -rf "$FIXTURE"
mkdir -p "$RELEASES" "$SCHEDULER"

# ---------------------------------------------------------------------------
# A repo to build releases from
# ---------------------------------------------------------------------------
# make_release.sh builds from git at HEAD and refuses a dirty tree, so it needs a repo -
# but the work in progress here is uncommitted, and committing it is the admin's
# decision, not this script's. So the working tree is copied into a throwaway repo and
# committed there.
echo "==> Copying the working tree into a throwaway repo"
mkdir -p "$BUILD"
rsync -a --exclude='.git/' --exclude='audio/' --exclude='dist/' \
         --exclude='__pycache__/' --exclude='_archive_scheduler/' \
         "$REPO_ROOT/" "$BUILD/"
printf '%s' "$HEALTH_STUB" > "$BUILD/$SUBTREE/config/scripts/health_check.sh"

git -C "$BUILD" init -q
git -C "$BUILD" config user.email "fixture@localhost"
git -C "$BUILD" config user.name "fixture"
git -C "$BUILD" add -A
git -C "$BUILD" commit -qm "fixture 1.0.0"

build_release() {
    local version="$1"
    echo "==> Building pi4 $version"
    (cd "$BUILD" && bash tools/make_release.sh pi4 "$version" > /dev/null)
    mkdir -p "$RELEASES/pi4-v$version"
    cp "$BUILD/dist/scheduler-pi4-$version.tar.gz" \
       "$BUILD/dist/version.json" "$BUILD/dist/SHA256SUMS" "$RELEASES/pi4-v$version/"
}

build_release 1.0.0

# 1.1.0 has to differ from 1.0.0 in a file the updater actually copies, otherwise
# "did the update land?" cannot be told apart from "did nothing happen?".
echo "# fixture marker: version 1.1.0" \
    >> "$BUILD/$SUBTREE/applications/desktop/prayer_times_gui/main.py"
git -C "$BUILD" commit -qam "fixture 1.1.0"
build_release 1.1.0

# The releases API returns a list of releases; the updater only reads tag_name, and
# ignores drafts and pre-releases.
cat > "$RELEASES/index.json" <<'INDEX'
[
  {"tag_name": "pi4-v1.1.0", "draft": false, "prerelease": false},
  {"tag_name": "pi4-v1.0.0", "draft": false, "prerelease": false}
]
INDEX

# The pointer that decides what the fixture device installs, and what it may replace.
# Starts at 1.1.0 so an unpinned run has somewhere to go; the tests move it to prove a
# fleet rollback, and add path rules to prove the include/exclude layer.
cat > "$RELEASES/VERSIONS.json" <<'POINTER'
{
  "pi4": {
    "version": "1.1.0",
    "exclude": [],
    "include": []
  },
  "zero": ""
}
POINTER

# ---------------------------------------------------------------------------
# A device
# ---------------------------------------------------------------------------
echo "==> Building the device tree"
rsync -a --exclude='audio/' --exclude='assets/' --exclude='__pycache__/' \
         --exclude='var/' --exclude='logs/' \
         "$TREE/" "$SCHEDULER/"
printf '%s' "$HEALTH_STUB" > "$SCHEDULER/config/scripts/health_check.sh"
mkdir -p "$SCHEDULER/logs" "$SCHEDULER/var/update/rollback" "$SCHEDULER/audio/fajr"

# The three kinds of state an update must leave alone, each marked so the tests can
# prove it survived byte for byte.
echo "FIXTURE-AUDIO" > "$SCHEDULER/audio/fajr/athan.mp3"
python3 - "$SCHEDULER/config/config.ini" <<'INI'
import configparser, sys
path = sys.argv[1]
parser = configparser.ConfigParser()
parser.read(path)
if not parser.has_section("Settings"):
    parser.add_section("Settings")
parser.set("Settings", "listen_to_quran", "04:44")
parser.write(open(path, "w"))
INI
printf 'prayerTimes = [{"Month":"1","Day":"1","Fajr":"05:00","Dhuhr":"12:34",\n' \
    > "$SCHEDULER/config/prayer_times_map.py"
printf '"Asr":"15:00","Maghrib":"18:00","Isha":"19:30","Shorooq":"06:30"}]\n' \
    >> "$SCHEDULER/config/prayer_times_map.py"
cp "$SCHEDULER/config/prayer_times_map.py" \
   "$SCHEDULER/applications/desktop/prayer_times_gui/prayer_times_map.py"

# The Settings app blocks on a mandatory picker if the owner's own prayer-times CSV is
# missing from the Desktop, which it would be on a fixture - so seed it from the shipped
# preset. This is a device file, not a release file: no update ever writes it.
cp "$SCHEDULER/config/prayers-config/برلين.csv" \
   "$DEV/Desktop/إدخال-مواقيت-الصلاة-للمستخدم.csv"

echo "1.0.0" > "$SCHEDULER/var/installed_version"

sed -e "s|^VARIANT=.*|VARIANT=pi4|" \
    -e "s|^#UPDATE_POINTER_URL=.*|UPDATE_POINTER_URL=\"file://$RELEASES/VERSIONS.json\"|" \
    -e "s|^#UPDATE_API_URL=.*|UPDATE_API_URL=\"file://$RELEASES/index.json\"|" \
    -e "s|^#UPDATE_DOWNLOAD_URL=.*|UPDATE_DOWNLOAD_URL=\"file://$RELEASES\"|" \
    "$SCHEDULER/config/update.conf.example" > "$SCHEDULER/config/update.conf"

# The hardware answer the updater cross-checks against. The tests point
# DEVICE_MODEL_FILE at this instead of /proc/device-tree/model.
echo "Raspberry Pi 4 Model B Rev 1.5" > "$FIXTURE/fake_model"

cp "$(dirname "${BASH_SOURCE[0]}")/test_updater.sh" \
   "$(dirname "${BASH_SOURCE[0]}")/test_state_survives.sh" \
   "$(dirname "${BASH_SOURCE[0]}")/test_settings_updates.py" \
   "$(dirname "${BASH_SOURCE[0]}")/test_friday_quran.py" "$FIXTURE/"
chmod +x "$FIXTURE/test_updater.sh" "$FIXTURE/test_state_survives.sh"

cat <<DONE

Fixture ready. Run the tests from inside it:

  bash $FIXTURE/test_updater.sh
  bash $FIXTURE/test_state_survives.sh
  python3 $FIXTURE/test_settings_updates.py
  python3 $FIXTURE/test_friday_quran.py

Poke at the device by hand the same way - HOME and the model file are all that make it
a device:

  HOME=$DEV DEVICE_MODEL_FILE=$FIXTURE/fake_model \\
      bash $SCHEDULER/config/scripts/check_updates.sh --status

Nothing here touches the real repo, and no release is published.
DONE
