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
rm -rf "$TREE/default-audio/fajr"
# Section 4 deletes and commits default-audio/shorooq/sunrise.mp3 - that is the whole
# point of it - so put the fixture's file back before starting, or every run after the
# first finds nothing to flag. Restored before the reset commit, since the build refuses
# a dirty tree.
mkdir -p "$TREE/default-audio/shorooq"
[ -f "$TREE/default-audio/shorooq/sunrise.mp3" ] \
    || printf 'fixture default audio\n' > "$TREE/default-audio/shorooq/sunrise.mp3"
git -C "$BUILD" add -f "$SUB/default-audio/shorooq/sunrise.mp3" > /dev/null 2>&1
git -C "$BUILD" add -A > /dev/null 2>&1
git -C "$BUILD" commit -qm "reset before run" > /dev/null 2>&1
rm -f "$BUILD/dist/scheduler-pi4-2."*.tar.gz
git -C "$BUILD" tag -d pi4-v2.0.9 > /dev/null 2>&1

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

echo "4. default-audio left over from the last release is caught"
# The throwaway repo has no remote, so the check falls back to local tags - which is the
# same path an offline build takes. sunrise.mp3 is already in default-audio/shorooq/, so
# tagging HEAD makes it "a file the last release shipped".
git -C "$BUILD" tag -f pi4-v2.0.9 > /dev/null 2>&1
out="$(build 2.1.0 < /dev/null)"
grep -q "already shipped in pi4-v2.0.9" <<< "$out" \
    && echo "  ✓ the leftover file is named" || { echo "  ✗ the leftover was not noticed"; fail=1; }
grep -q "default-audio/shorooq/sunrise.mp3" <<< "$out" \
    && echo "  ✓ with its path" || { echo "  ✗ the path was not shown"; fail=1; }
grep -q "refusing to ship default-audio" <<< "$out" \
    && echo "  ✓ with no terminal it refuses rather than hangs" || { echo "  ✗ it did not refuse"; fail=1; }
[ ! -f "$BUILD/dist/scheduler-pi4-2.1.0.tar.gz" ] \
    && echo "  ✓ and nothing was built" || { echo "  ✗ it built anyway"; fail=1; }

out="$(build 2.1.0 --keep-default-audio < /dev/null)"
grep -q "as asked" <<< "$out" \
    && echo "  ✓ --keep-default-audio ships it deliberately" || { echo "  ✗ the flag did not apply"; fail=1; }
grep -q "sha256" <<< "$out" \
    && echo "  ✓ and the build completes" || { echo "  ✗ the build did not finish"; fail=1; }

# The prompt asks about the release, not about the deletion: yes ships them again, no
# cleans up and stops. It only appears on a terminal - by design, so a scripted build
# cannot be made to delete files by accident - so this needs a pty rather than a pipe.
pty_build() { (cd "$BUILD" && printf '%s\n' "$1" | script -qec "bash tools/make_release.sh pi4 $2" /dev/null 2>&1); }

out="$(pty_build y 2.1.1)"
grep -q "shipping them again" <<< "$out" \
    && echo "  ✓ answering yes releases with them" || { echo "  ✗ yes did not proceed"; fail=1; }
[ -f "$TREE/default-audio/shorooq/sunrise.mp3" ] \
    && echo "  ✓ and nothing was deleted" || { echo "  ✗ yes deleted the file"; fail=1; }

out="$(pty_build n 2.1.2)"
grep -q "Removed, and the release stopped" <<< "$out" \
    && echo "  ✓ answering no cleans up instead" || { echo "  ✗ no did not clean up"; fail=1; }
[ ! -f "$TREE/default-audio/shorooq/sunrise.mp3" ] \
    && echo "  ✓ the file is gone from the tree" || { echo "  ✗ the file survived"; fail=1; }
grep -q "git commit -m" <<< "$out" \
    && echo "  ✓ and the commit command is printed" || { echo "  ✗ no commit instructions"; fail=1; }
grep -q "git push" <<< "$out" \
    && echo "  ✓ along with the push" || { echo "  ✗ no push instruction"; fail=1; }
[ ! -f "$BUILD/dist/scheduler-pi4-2.1.2.tar.gz" ] \
    && echo "  ✓ and no release was built" || { echo "  ✗ it built from a dirty tree"; fail=1; }

# Once it is committed away, the next build is clean again.
commit "clear default-audio"
out="$(build 2.1.3 < /dev/null)"
grep -q "nothing here was in pi4-v2.0.9" <<< "$out" \
    && echo "  ✓ the next release passes the check" || { echo "  ✗ still flagged"; fail=1; }

# Audio added for this release is an intentional act and must never be questioned.
mkdir -p "$TREE/default-audio/fajr"
echo new > "$TREE/default-audio/fajr/brand-new.mp3"
git -C "$BUILD" add -f "$SUB/default-audio/fajr/brand-new.mp3" > /dev/null 2>&1
commit "audio meant for this release"
out="$(build 2.1.4 < /dev/null)"
grep -q "already shipped" <<< "$out" \
    && { echo "  ✗ new audio was questioned"; fail=1; } || echo "  ✓ new audio is not questioned"
grep -q "brand-new.mp3" <<< "$out" \
    && { echo "  ✗ new audio was named to the admin"; fail=1; } || echo "  ✓ and not mentioned at all"
listing 2.1.4 | grep -q "default-audio/fajr/brand-new.mp3" \
    && echo "  ✓ and it ships" || { echo "  ✗ new audio did not ship"; fail=1; }
rm -rf "$TREE/default-audio/fajr"; commit "remove new audio"

echo "5. a version that is already published is refused"
out="$(build 2.0.9 < /dev/null)"
grep -q "already published" <<< "$out" \
    && echo "  ✓ rebuilding a published version is refused" || { echo "  ✗ a republish was allowed"; fail=1; }
git -C "$BUILD" tag -d pi4-v2.0.9 > /dev/null 2>&1

echo
[ $fail -eq 0 ] && echo "ALL PASS" || echo "FAILURES ABOVE"
