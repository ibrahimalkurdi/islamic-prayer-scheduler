#!/bin/bash
# Mirror this repo, and one release, to Codeberg.
#
#   tools/mirror_codeberg.sh                    mirror the source tree only
#   tools/mirror_codeberg.sh pi4 1.1.5          and copy that release across
#
# GitHub stays the repo of record. Codeberg exists because raw.githubusercontent.com and
# objects.githubusercontent.com are blocked in Syria, which is every host a device
# fetches from - so devices there read nothing at all, not even the version pointer.
# check_updates.sh falls back to Codeberg on its own; this is what keeps Codeberg worth
# falling back to.
#
# The two repos have unrelated histories - Codeberg was seeded from a content copy, not a
# clone - so this syncs the tree and commits, rather than pushing. The commit message is
# GitHub's own, so the same change reads the same way on both.
#
# Release assets go up through Gitea's API, which needs a token with repository write:
#   https://codeberg.org/user/settings/applications
# then either CODEBERG_TOKEN in the environment, or ~/.config/codeberg/token.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIRROR="${CODEBERG_DIR:-$HOME/codeberg/islamic-prayer-scheduler}"
OWNER="teleshops"
NAME="islamic-prayer-scheduler"
API="https://codeberg.org/api/v1/repos/$OWNER/$NAME"
OUT_DIR="$REPO_ROOT/dist"

usage() {
    cat >&2 <<'USAGE'
usage: mirror_codeberg.sh [<pi4|zero> <version>]

  no arguments   mirror the source tree and push it
  variant+version
                 also create the matching Codeberg release and upload
                 dist/<archive>, dist/version.json and dist/SHA256SUMS to it.
                 Run this after `gh release create`, so the title and notes can
                 be copied from the GitHub release rather than invented here.
USAGE
    exit 2
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage
VARIANT="${1:-}"
VERSION="${2:-}"
[[ $# -eq 0 || $# -eq 2 ]] || usage

TAG=""
if [[ -n "$VARIANT" ]]; then
    case "$VARIANT" in
        pi4|zero) ;;
        *) echo "ERROR: unknown variant '$VARIANT'" >&2; usage ;;
    esac
    [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
        || { echo "ERROR: version must look like 1.2.3, got '$VERSION'" >&2; exit 2; }
    TAG="${VARIANT}-v${VERSION}"
fi

cd "$REPO_ROOT"

# What goes out is a commit, not a working tree. Mirroring uncommitted edits would put
# something on Codeberg that exists nowhere else, and devices would install it.
if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree is dirty - commit or stash first" >&2
    git status --short >&2
    exit 1
fi

[[ -d "$MIRROR/.git" ]] || {
    echo "ERROR: no Codeberg checkout at $MIRROR" >&2
    echo "       git clone ssh://git@codeberg.org/$OWNER/$NAME.git \"$MIRROR\"" >&2
    echo "       or set CODEBERG_DIR to where it lives." >&2
    exit 1
}

SOURCE_SHA="$(git rev-parse HEAD)"
SOURCE_SHORT="$(git rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
# 1. the source tree
# ---------------------------------------------------------------------------
echo "==> Mirroring the tree at $SOURCE_SHORT into $MIRROR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
git archive --format=tar HEAD | tar -x -C "$WORK"

# --delete so a file removed here is removed there. dist/ is build output on both sides
# and ignored by both, but it is where the tarballs sit - so it is left alone rather
# than swept away by a mirror run.
rsync -a --delete \
      --exclude '.git/' --exclude 'dist/' --exclude '__pycache__/' \
      "$WORK/" "$MIRROR/"

git -C "$MIRROR" add -A
if git -C "$MIRROR" diff --cached --quiet; then
    echo "    already identical - nothing to commit"
else
    # GitHub's own message, so the same change reads the same way in both histories.
    # The trailer is the only way back: the histories are unrelated, so the SHAs cannot
    # be compared and nothing else records which commit a mirror commit came from.
    {
        git log -1 --format=%B "$SOURCE_SHA"
        echo "Mirrored-from: $SOURCE_SHA"
    } > "$WORK/msg"
    git -C "$MIRROR" commit -q -F "$WORK/msg"
    echo "    committed $(git -C "$MIRROR" rev-parse --short HEAD)"
fi

echo "==> Pushing to Codeberg"
git -C "$MIRROR" push -q origin HEAD
echo "    pushed"

[[ -n "$TAG" ]] || {
    echo
    echo "Tree mirrored. No release asked for - pass a variant and version to copy one."
    exit 0
}

# ---------------------------------------------------------------------------
# 2. the release
# ---------------------------------------------------------------------------
TOKEN="${CODEBERG_TOKEN:-}"
TOKEN_FILE="$HOME/.config/codeberg/token"
[[ -z "$TOKEN" && -f "$TOKEN_FILE" ]] && TOKEN="$(tr -d '[:space:]' < "$TOKEN_FILE")"
if [[ -z "$TOKEN" ]]; then
    echo "ERROR: no Codeberg token - the tree is mirrored, the release is not." >&2
    echo "       Make one with repository write at" >&2
    echo "         https://codeberg.org/user/settings/applications" >&2
    echo "       then put it in $TOKEN_FILE (chmod 600) or CODEBERG_TOKEN," >&2
    echo "       and run this again. Nothing above needs repeating." >&2
    exit 1
fi

ARCHIVE_NAME="scheduler-${VARIANT}-${VERSION}.tar.gz"
ASSETS=("$OUT_DIR/$ARCHIVE_NAME" "$OUT_DIR/version.json" "$OUT_DIR/SHA256SUMS")
for asset in "${ASSETS[@]}"; do
    [[ -f "$asset" ]] || {
        echo "ERROR: missing $asset - build it first with:" >&2
        echo "       tools/make_release.sh $VARIANT $VERSION" >&2
        exit 1
    }
done

# The manifest names the version a device will install, and the archive it will trust.
# Mirroring one release's manifest under another release's tag would hand devices a
# checksum for a file they are not being given.
MANIFEST_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' \
                    "$OUT_DIR/version.json")"
[[ "$MANIFEST_VERSION" == "$VERSION" ]] || {
    echo "ERROR: dist/version.json is for $MANIFEST_VERSION, not $VERSION." >&2
    echo "       dist/ holds the last build - rebuild $VERSION before mirroring it." >&2
    exit 1
}

api() {
    local method="$1" path="$2"; shift 2
    curl --silent --show-error --location \
         --header "Authorization: token $TOKEN" \
         --request "$method" "$API$path" "$@"
}

# Same call, but keeping the body and the status code. Gitea says why it refused, and
# the reasons are not interchangeable - a missing unit, a token that cannot write, and
# a tag that already exists all arrive here and need different things done about them.
api_checked() {
    local method="$1" path="$2"; shift 2
    local out status
    out="$(curl --silent --show-error --location --write-out '\n%{http_code}' \
                --header "Authorization: token $TOKEN" \
                --request "$method" "$API$path" "$@")"
    status="${out##*$'\n'}"
    API_BODY="${out%$'\n'*}"
    API_STATUS="$status"
    [[ "$status" =~ ^2 ]]
}

json_field() { python3 -c '
import json, sys
try: doc = json.load(sys.stdin)
except Exception: sys.exit(0)
v = doc.get(sys.argv[1]) if isinstance(doc, dict) else None
if v is not None: print(v)
' "$1"; }

# Releases are a repository "unit" in Gitea and ship disabled on a new repo. With the
# unit off there is no /releases endpoint at all, so every call below 404s - which reads
# exactly like a permissions problem and is not one. Checked first, by name.
HAS_RELEASES="$(api GET "" | python3 -c '
import json, sys
try: print(json.load(sys.stdin).get("has_releases"))
except Exception: print("unknown")
')"
if [[ "$HAS_RELEASES" == "False" ]]; then
    cat >&2 <<UNITS
ERROR: Releases are switched off on this repository, so it has no /releases endpoint
       and nothing can be uploaded. The tree is mirrored; only this step is blocked.

       Turn it on:
         https://codeberg.org/$OWNER/$NAME/settings
         -> Units -> tick "Releases" -> Update Settings

       then run this again. Nothing above needs repeating.
UNITS
    exit 1
fi

echo "==> Codeberg release $TAG"
RELEASE_ID="$(api GET "/releases/tags/$TAG" | json_field id)"

if [[ -n "$RELEASE_ID" ]]; then
    echo "    already there (id $RELEASE_ID) - filling in whatever is missing"
else
    # Same title and notes as GitHub's, when GitHub's exists - the point is one release
    # in two places, not two releases that happen to share a version number.
    TITLE="$VARIANT $VERSION"
    BODY=""
    if command -v gh > /dev/null && gh release view "$TAG" > /dev/null 2>&1; then
        TITLE="$(gh release view "$TAG" --json name --jq '.name // ""')"
        BODY="$(gh release view "$TAG" --json body --jq '.body // ""')"
        echo "    copying the title and notes from the GitHub release"
    else
        echo "    no GitHub release for $TAG yet - using a plain title" >&2
    fi
    [[ -n "$TITLE" ]] || TITLE="$VARIANT $VERSION"

    PAYLOAD="$(python3 -c '
import json, sys
print(json.dumps({"tag_name": sys.argv[1], "target_commitish": sys.argv[2],
                  "name": sys.argv[3], "body": sys.argv[4]}))
' "$TAG" "$(git -C "$MIRROR" rev-parse --abbrev-ref HEAD)" "$TITLE" "$BODY")"

    if ! api_checked POST "/releases" \
                     --header "Content-Type: application/json" \
                     --data "$PAYLOAD"; then
        echo "ERROR: could not create the release (HTTP $API_STATUS)" >&2
        echo "       $(printf '%s' "$API_BODY" | head -c 400)" >&2
        exit 1
    fi
    RELEASE_ID="$(printf '%s' "$API_BODY" | json_field id)"
    [[ -n "$RELEASE_ID" ]] || {
        echo "ERROR: the release was created but returned no id - check it by hand:" >&2
        echo "       https://codeberg.org/$OWNER/$NAME/releases" >&2
        exit 1
    }
    echo "    created (id $RELEASE_ID)"
fi

EXISTING="$(api GET "/releases/$RELEASE_ID/assets" | python3 -c '
import json, sys
try: assets = json.load(sys.stdin)
except Exception: assets = []
for a in assets if isinstance(assets, list) else []:
    print(a.get("name", ""))
')"

for asset in "${ASSETS[@]}"; do
    base="$(basename "$asset")"
    if grep -qxF "$base" <<< "$EXISTING"; then
        echo "    $base is already uploaded - left alone"
        continue
    fi
    if ! api_checked POST "/releases/$RELEASE_ID/assets?name=$base" \
                     --form "attachment=@$asset"; then
        echo "ERROR: upload failed for $base (HTTP $API_STATUS)" >&2
        echo "       $(printf '%s' "$API_BODY" | head -c 400)" >&2
        exit 1
    fi
    echo "    uploaded $base"
done

# What a device will actually ask for. A release that exists but serves no manifest is
# the failure that sends a device round the rollback path, so it is checked from outside
# the API rather than assumed from the upload.
DOWNLOAD="https://codeberg.org/$OWNER/$NAME/releases/download/$TAG"
echo "==> Checking the mirror the way a device will"
for file in "version.json" "$ARCHIVE_NAME"; do
    code="$(curl --silent --location --output /dev/null --write-out '%{http_code}' \
                 --max-time 60 "$DOWNLOAD/$file")"
    [[ "$code" == "200" ]] || { echo "ERROR: $DOWNLOAD/$file answered $code" >&2; exit 1; }
    echo "    $file 200"
done

POINTER="https://codeberg.org/$OWNER/$NAME/raw/branch/$(git -C "$MIRROR" rev-parse --abbrev-ref HEAD)/VERSIONS.json"
MIRRORED_TARGET="$(curl --silent --location --max-time 30 "$POINTER" \
                   | python3 -c '
import json, sys
try: doc = json.load(sys.stdin)
except Exception: sys.exit(0)
v = doc.get(sys.argv[1])
print(v.get("version") if isinstance(v, dict) else (v or ""))
' "$VARIANT" 2>/dev/null || true)"

cat <<SUMMARY

  tag        $TAG
  release    https://codeberg.org/$OWNER/$NAME/releases/tag/$TAG
  pointer    $VARIANT -> ${MIRRORED_TARGET:-unreadable}

SUMMARY

if [[ "$MIRRORED_TARGET" != "$VERSION" ]]; then
    cat <<NOTE
The mirrored pointer still says "${MIRRORED_TARGET:-nothing}", so no device will install
$VERSION from either host yet. That is the normal order - the release goes up first, and
VERSIONS.json is edited afterwards, once it has been tried on one device. Run this script
again after pushing that edit, so both hosts agree on the target.
NOTE
fi
