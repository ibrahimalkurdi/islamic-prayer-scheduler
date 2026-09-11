#!/bin/bash
# The packaging guards: what may ship, what may not, and what has to be asked about
# before it does. Runs against the throwaway repo the fixture builds, so the real repo is
# never touched and nothing is published.
#
#   bash tools/tests/make_fixture.sh
#   bash /tmp/scheduler-update-test/test_make_release.sh
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/build-repo"
TREE="$BUILD/scheduler-official-touch-screen-with-raspberry-pi-4"
fail=0
chk() { if [ "$2" = "$3" ]; then echo "  ✓ $1"; else echo "  ✗ $1 — expected $3, got $2"; fail=1; fi; }

build() { (cd "$BUILD" && bash tools/make_release.sh pi4 "$@" 2>&1); }
commit() { git -C "$BUILD" add -A && git -C "$BUILD" commit -qm "$1" > /dev/null 2>&1; true; }
listing() { tar -tzf "$BUILD/dist/scheduler-pi4-$1.tar.gz"; }

# This suite commits to the throwaway repo as it goes. An interrupted run leaves those
# commits behind and every later run then fails on them, so it starts by undoing its own.
SUB="scheduler-official-touch-screen-with-raspberry-pi-4"
git -C "$BUILD" rm -q --cached "$SUB/config/scripts/stray.mp3" > /dev/null 2>&1
rm -f "$TREE/config/scripts/stray.mp3"
rm -rf "$TREE/default-audio/shroq"
git -C "$BUILD" add -A > /dev/null 2>&1
git -C "$BUILD" commit -qm "reset before run" > /dev/null 2>&1
rm -f "$BUILD/dist/scheduler-pi4-2."*.tar.gz

echo "1. default-audio ships; an MP3 anywhere else does not"
out="$(build 2.0.0)"; chk "the build succeeds" "$?" "0"
listing 2.0.0 | grep -q "default-audio/shorooq/sunrise.mp3" \
    && echo "  ✓ the release carries default-audio" || { echo "  ✗ default-audio was stripped"; fail=1; }
listing 2.0.0 | grep -q "^./audio/" \
    && { echo "  ✗ the owner's audio folder shipped"; fail=1; } || echo "  ✓ audio/ itself is still stripped"

# .gitignore keeps stray MP3s out of the repo in the first place, so getting one into a
# release takes -f. That is the case the leak check exists for: the ignore rule changing,
# or someone forcing a file in without thinking about where it lands.
mkdir -p "$TREE/config/scripts"
echo "not audio" > "$TREE/config/scripts/stray.mp3"
git -C "$BUILD" add -f "scheduler-official-touch-screen-with-raspberry-pi-4/config/scripts/stray.mp3"
git -C "$BUILD" commit -qm "a stray mp3" > /dev/null 2>&1
out="$(build 2.0.1)"
grep -q "LEAKED: ./config/scripts/stray.mp3" <<< "$out" \
    && echo "  ✓ an MP3 outside default-audio fails the build" || { echo "  ✗ a stray MP3 shipped"; fail=1; }
git -C "$BUILD" rm -q --cached "scheduler-official-touch-screen-with-raspberry-pi-4/config/scripts/stray.mp3" > /dev/null
rm -f "$TREE/config/scripts/stray.mp3"; commit "remove stray"

echo "2. a folder name that matches no event is questioned"
mkdir -p "$TREE/default-audio/shroq"
echo x > "$TREE/default-audio/shroq/typo.mp3"
commit "a misspelled event folder"
out="$(build 2.0.2 < /dev/null)"
grep -q "does not match any audio folder" <<< "$out" \
    && echo "  ✓ the name is reported" || { echo "  ✗ the typo passed unnoticed"; fail=1; }
grep -q "Did you mean: shorooq" <<< "$out" \
    && echo "  ✓ and the real name is suggested" || { echo "  ✗ no suggestion offered"; fail=1; }
grep -q "refusing to build" <<< "$out" \
    && echo "  ✓ with no terminal it refuses rather than hangs" || { echo "  ✗ it did not refuse"; fail=1; }
out="$(build 2.0.2 --yes < /dev/null)"
grep -q "sha256" <<< "$out" \
    && echo "  ✓ --yes builds it anyway" || { echo "  ✗ --yes did not proceed"; fail=1; }
rm -rf "$TREE/default-audio/shroq"; commit "remove typo folder"

echo "3. the payload size is capped"
out="$(MAX_RELEASE_MB=1 build 2.0.3 < /dev/null)"
grep -q "over the 1 MB limit" <<< "$out" \
    && echo "  ✓ an oversized payload is refused" || { echo "  ✗ the cap did not fire"; fail=1; }
[ ! -f "$BUILD/dist/scheduler-pi4-2.0.3.tar.gz" ] \
    && echo "  ✓ and the archive is not left behind" || { echo "  ✗ the archive survived"; fail=1; }
out="$(MAX_RELEASE_MB=1 build 2.0.3 --allow-large < /dev/null)"
grep -q "sha256" <<< "$out" \
    && echo "  ✓ --allow-large builds it" || { echo "  ✗ --allow-large did not proceed"; fail=1; }

echo
[ $fail -eq 0 ] && echo "ALL PASS" || echo "FAILURES ABOVE"
