#!/bin/bash
# The choices release.sh makes on its own: the next version, the suggested notes, whether
# the fleet Worker needs deploying, and the VERSIONS.json edit. Runs in a throwaway repo,
# so nothing is built, pushed or published.
#
#   bash tools/tests/test_release.sh
HERE="$(cd "$(dirname "$0")" && pwd)"
source "$HERE/../release.sh"
set +e
fail=0
chk() { if [ "$2" = "$3" ]; then echo "  ✓ $1"; else echo "  ✗ $1 — expected [$3], got [$2]"; fail=1; fi; }

echo "== versions"
TAGS=$'v0.1.0\npi4-v1.6.9\npi4-v1.6.10\npi4-v1.5.0\nzero-v2.0.0\npi4-vbad'
chk "highest pi4 by version, not by text" "$(latest_version pi4 <<< "$TAGS")" "1.6.10"
chk "variants do not mix" "$(latest_version zero <<< "$TAGS")" "2.0.0"
chk "no release yet" "$(latest_version zero <<< "v0.1.0")" ""
chk "next patch" "$(next_patch 1.6.10)" "1.6.11"
chk "first release" "$(next_patch "")" "0.1.0"

REPO="$(mktemp -d)"
trap 'rm -rf "$REPO"' EXIT
cd "$REPO" || exit 1
git init -q -b main
git config user.email t@example.com
git config user.name t
c() { mkdir -p "$(dirname "$1")"; echo "$RANDOM" >> "$1"; git add -A; git commit -qm "$2"; }
c a.txt "Old change"
git tag pi4-v1.0.0

echo "== notes"
c a.txt "Fix the countdown"
c b.txt "static website: rebuild alsakina (2026-10-12)"
c a.txt "Roll pi4 out to 1.0.0"
c a.txt "Add a city"
chk "only real changes since the last tag" "$(suggest_notes pi4-v1.0.0)" $'- Add a city\n- Fix the countdown'
chk "everything when there is no tag" "$(suggest_notes "" | wc -l)" "3"

echo "== worker"
worker_changed pi4-v1.0.0; chk "untouched worker is skipped" "$?" "1"
c tools/report-worker/README.md "Worker docs"
worker_changed pi4-v1.0.0; chk "a README change is not a deploy" "$?" "1"
c tools/report-worker/worker.js "Worker code"
worker_changed pi4-v1.0.0; chk "a code change deploys" "$?" "0"
worker_changed ""; chk "no previous release deploys" "$?" "0"

echo "== pointer"
cat > VERSIONS.json <<'JSON'
{
  "_readme": { "examples": { "x": { "version": "1.1.0" }, "pi4": "nope" } },

  "pi4": {
    "version": "1.6.4",
    "exclude": [],
    "include": []
  },

  "zero": "1.0.0"
}
JSON
set_pointer VERSIONS.json pi4 1.6.5 2> /dev/null
chk "the _readme example is untouched" "$(grep -c '"version": "1.1.0"' VERSIONS.json)" "1"
python3 - <<'PY' > got
import json; d = json.load(open("VERSIONS.json")); print(d["pi4"]["version"], d["zero"], d["_readme"]["examples"]["pi4"])
PY
chk "pi4 block moved, the rest kept" "$(cat got)" "1.6.5 1.0.0 nope"
chk "layout kept" "$(grep -c '^$' VERSIONS.json)" "2"
set_pointer VERSIONS.json zero 1.0.1 2> /dev/null
chk "the short form is edited too" "$(python3 -c 'import json; print(json.load(open("VERSIONS.json"))["zero"])')" "1.0.1"
set_pointer VERSIONS.json nope 1.0.0 2> /dev/null; chk "an unknown variant fails" "$?" "1"

echo
[ $fail -eq 0 ] && echo "ALL PASS" || { echo "FAILURES ABOVE"; exit 1; }
