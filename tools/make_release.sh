#!/bin/bash
# Package one device build for publishing.
#
#   tools/make_release.sh <variant> <version>      e.g. tools/make_release.sh pi4 1.1.0
#
# Runs from the repo, never from a device. Produces the tarball, its checksum, and the
# manifest a device reads to decide what to replace - then prints the gh command to
# publish them.
#
# The one thing this must never do is ship device state. A device's config.ini holds the
# owner's settings and the generated CSVs hold their prayer times, and both are tracked
# in git, so they are in HEAD and would land in a naive archive. They are stripped here,
# and step 4 then proves they are gone rather than trusting the strip.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$REPO_ROOT/dist"

usage() {
    echo "usage: $(basename "$0") <pi4|zero> <version>" >&2
    exit 2
}

[[ $# -eq 2 ]] || usage
VARIANT="$1"
VERSION="$2"

case "$VARIANT" in
    pi4)  SUBTREE="scheduler-official-touch-screen-with-raspberry-pi-4" ;;
    zero) SUBTREE="scheduler-unofficial-touch-screen-with-raspberry-zero" ;;
    *)    echo "ERROR: unknown variant '$VARIANT'" >&2; usage ;;
esac

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
    || { echo "ERROR: version must look like 1.2.3, got '$VERSION'" >&2; exit 2; }

TAG="${VARIANT}-v${VERSION}"
ARCHIVE_NAME="scheduler-${VARIANT}-${VERSION}.tar.gz"

cd "$REPO_ROOT"

# Committed content only. A release built from a dirty tree cannot be reproduced later,
# and this is the artefact that goes out to every device.
if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree is dirty - commit or stash first" >&2
    git status --short >&2
    exit 1
fi
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "ERROR: tag $TAG already exists" >&2
    exit 1
fi
[[ -d "$SUBTREE" ]] || { echo "ERROR: no such tree: $SUBTREE" >&2; exit 1; }

# Device state. Never shipped: the archive would overwrite the owner's own copies.
# Also the docs and screenshots, which no device reads.
STRIP=(
    "audio" "assets" "logs" "var"
    "README.md" "USER_MANUAL_AR.md"
    "config/config.ini" "config/update.conf"
    "config/input-prayers-time.csv" "config/prayer_times.csv"
    "config/prayer_times_map.py" "config/executed-events.json"
    "applications/desktop/prayer_times_gui/prayer_times_map.py"
    # Raw imports are the owner's own exports, kept as a record of what they fed in.
    # The presets beside them ship on purpose; this one directory does not.
    "config/prayers-config/raw-imports"
)

# Prayer-time presets that ship on purpose. Every other *.csv is generated from one
# device's own data and must never travel to another.
SHIPPED_CSV_NAME="default-prayers-time.csv"

# What a device may replace. Everything else in its tree is left alone, so a state file
# added in some later version cannot be clobbered by an updater that predates it.
INCLUDE=(
    "applications/"
    "config/scripts/"
    "config/systemd/"
    "config/prayer_times_gui.desktop"
    "config/scheduler_settings_gui.desktop"
    "config/pipewire-pulse.conf"
    "config/crontab.txt"
    "config/update.conf.example"
)
# Belt and braces beside the strip above: rsync honours these on the device, so even a
# state file that somehow survived packaging would not be copied over the live one.
EXCLUDE=(
    "config/config.ini" "config/update.conf"
    "config/*.csv" "config/executed-events.json"
    "**/prayer_times_map.py" "**/__pycache__/" "*.pyc"
    "audio/" "var/" "logs/"
)

mkdir -p "$OUT_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> Exporting $SUBTREE at HEAD"
git archive --format=tar "HEAD:$SUBTREE" | tar -x -C "$WORK"

# The two trees keep their fonts and presets in different places, and an empty
# directory left behind by a rename must not end up in the list either - so this asks
# the exported tree what is really there, not the checkout.
for optional in "config/fonts/" "config/icons/" "config/arabic-fonts/" "config/prayers-config/"; do
    if [[ -d "$WORK/${optional%/}" ]] && [[ -n "$(ls -A "$WORK/${optional%/}")" ]]; then
        INCLUDE+=("$optional")
    fi
done

echo "==> Stripping device state"
for path in "${STRIP[@]}"; do
    if [[ -e "$WORK/$path" ]]; then
        rm -rf "${WORK:?}/$path"
        echo "    removed $path"
    fi
done
find "$WORK" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$WORK" -name '*.pyc' -delete 2>/dev/null || true

# Prove it, rather than trusting it. This is the check that stands between a release and
# shipping someone's settings to every device that installs it.
echo "==> Verifying nothing private survived"
LEAKED=0
while IFS= read -r found; do
    echo "    LEAKED: $found" >&2
    LEAKED=1
done < <(cd "$WORK" && {
    find . \( -name 'config.ini' -o -name 'prayer_times_map.py' \
           -o -name 'executed-events.json' -o -name '*.mp3' \
           -o -path './audio/*' -o -path './var/*' -o -path './logs/*' \) -print
    # A CSV only ships if it is a preset: named default-prayers-time.csv, or sitting in
    # the presets directory. Anything else is one device's own prayer times.
    find . -name '*.csv' \
         ! -name "$SHIPPED_CSV_NAME" \
         ! -path './config/prayers-config/*' -print
} 2>/dev/null)
if [[ $LEAKED -eq 1 ]]; then
    echo "ERROR: device state is still in the archive - refusing to build" >&2
    exit 1
fi
echo "    clean"

# Sanity: the thing a device actually runs has to be in there.
for required in "applications/desktop/prayer_times_gui/main.py" \
                "config/scripts/check_updates.sh" "config/scripts/health_check.sh" \
                "config/scripts/set_device_user.sh"; do
    [[ -f "$WORK/$required" ]] || { echo "ERROR: missing from archive: $required" >&2; exit 1; }
done

echo "==> Building $ARCHIVE_NAME"
tar -czf "$OUT_DIR/$ARCHIVE_NAME" -C "$WORK" .
SHA256="$(cd "$OUT_DIR" && sha256sum "$ARCHIVE_NAME" | cut -d' ' -f1)"
(cd "$OUT_DIR" && sha256sum "$ARCHIVE_NAME" > SHA256SUMS)

echo "==> Writing version.json"
python3 - "$OUT_DIR/version.json" "$VARIANT" "$VERSION" "$ARCHIVE_NAME" "$SHA256" \
         "${INCLUDE[*]}" "${EXCLUDE[*]}" <<'MANIFEST'
import json, sys
path, variant, version, archive, sha256, include, exclude = sys.argv[1:8]
json.dump({
    "variant": variant,
    "version": version,
    "archive": archive,
    "sha256": sha256,
    "notes": "",
    "min_updater": "1.0.0",
    "apply_mode": "changed",
    "include": include.split(),
    "exclude": exclude.split(),
}, open(path, "w"), indent=2)
MANIFEST

SIZE="$(du -h "$OUT_DIR/$ARCHIVE_NAME" | cut -f1)"
cat <<SUMMARY

  variant   $VARIANT
  version   $VERSION
  tag       $TAG
  archive   dist/$ARCHIVE_NAME  ($SIZE)
  sha256    $SHA256

Edit dist/version.json to add release notes, then publish:

  gh release create $TAG \\
      dist/$ARCHIVE_NAME dist/version.json dist/SHA256SUMS \\
      --title "$VARIANT $VERSION" --notes "..."

Publishing does NOT roll it out. Devices install whatever VERSIONS.json names, so test
the release on one device first:

  ssh <device> 'bash ~/Desktop/scheduler/config/scripts/check_updates.sh --target $VERSION'

then roll the fleet forward by setting "$VARIANT" to "$VERSION" in VERSIONS.json and
pushing that one file. Setting it back to the previous version rolls everyone back.
The other variant is unaffected either way.
SUMMARY
