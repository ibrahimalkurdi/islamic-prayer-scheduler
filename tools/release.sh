#!/bin/bash
# Publish a release in one go: build, push, GitHub, Codeberg - and the fleet Worker when
# its code changed since the last release.
#
#   tools/release.sh                      pi4, next patch version, notes from git log
#   tools/release.sh pi4 1.7.0            pick the version
#   tools/release.sh --rollout pi4 1.6.6  point VERSIONS.json at a published release
#
# Asks once before anything leaves this machine. Rolling out stays a separate question,
# because a release is meant to be tried on one device before every device takes it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_DIR="tools/report-worker"
WORKER_FILES=("$WORKER_DIR/worker.js" "$WORKER_DIR/wrangler.toml")

usage() {
    cat >&2 <<'USAGE'
usage: release.sh [pi4|zero] [<version>]
       release.sh --rollout <pi4|zero> <version>
USAGE
    exit 2
}

latest_version() {
    grep "^$1-v" | sed "s|^$1-v||" | grep -E '^[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || true
}

next_patch() {
    [[ -n "$1" ]] || { echo "0.1.0"; return; }
    local major minor patch
    IFS=. read -r major minor patch <<< "$1"
    echo "$major.$minor.$((patch + 1))"
}

# Rebuilds of the static sites happen every few days and say nothing about the release.
suggest_notes() {
    local range="HEAD"
    [[ -n "$1" ]] && range="$1..HEAD"
    git log --no-merges --format='- %s' "$range" \
        | grep -vE '^- (static website: |Roll (pi4|zero) out to )' || true
}

worker_changed() {
    [[ -z "$1" ]] && return 0
    ! git diff --quiet "$1" HEAD -- "${WORKER_FILES[@]}"
}

# A regex, not json.dump: the file is laid out by hand and read by people.
set_pointer() {
    python3 - "$@" <<'PY'
import re, sys
path, variant, version = sys.argv[1:4]
text = open(path, encoding="utf-8").read()
block = re.compile(r'("%s"\s*:\s*\{[^{}]*?"version"\s*:\s*")[^"]*(")' % variant)
short = re.compile(r'("%s"\s*:\s*")[^"]*(")' % variant)
new, n = block.subn(lambda m: m.group(1) + version + m.group(2), text, count=1)
if n == 0:
    new, n = short.subn(lambda m: m.group(1) + version + m.group(2), text, count=1)
if n == 0:
    sys.exit(f"no '{variant}' entry in {path}")
open(path, "w", encoding="utf-8").write(new)
PY
}

ask() {
    local prompt="$1" default="$2" answer
    read -r -p "$prompt" answer
    echo "${answer:-$default}"
}

rollout() {
    local variant="$1" version="$2"
    set_pointer VERSIONS.json "$variant" "$version"
    if git diff --quiet -- VERSIONS.json; then
        echo "VERSIONS.json already names $variant $version"
        return
    fi
    git commit -q -m "Roll $variant out to $version" -- VERSIONS.json
    git push -q
    tools/mirror_codeberg.sh
    echo "Rolled out: $variant devices take $version at their next 02:00 check."
}

main() {
    cd "$REPO_ROOT"
    local mode=release
    [[ "${1:-}" == "--rollout" ]] && { mode=rollout; shift; }
    [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage
    local variant="${1:-pi4}" version="${2:-}"
    [[ "$variant" == pi4 || "$variant" == zero ]] || usage

    [[ -t 0 ]] || { echo "ERROR: release.sh asks questions - run it in a terminal" >&2; exit 1; }
    [[ -z "$(git status --porcelain)" ]] \
        || { echo "ERROR: working tree is dirty - commit or stash first" >&2; git status --short >&2; exit 1; }
    [[ "$(git rev-parse --abbrev-ref HEAD)" == main ]] \
        || { echo "ERROR: releases go out from main" >&2; exit 1; }

    if [[ "$mode" == rollout ]]; then
        [[ -n "$version" ]] || usage
        rollout "$variant" "$version"
        return
    fi

    for tool in gh python3; do
        command -v "$tool" > /dev/null || { echo "ERROR: $tool is not installed" >&2; exit 1; }
    done

    git fetch -q --tags origin
    local previous prev_tag=""
    previous="$(git tag | latest_version "$variant")"
    [[ -n "$previous" ]] && prev_tag="$variant-v$previous"

    if [[ -z "$version" ]]; then
        version="$(ask "Version (last ${previous:-none}) [$(next_patch "$previous")]: " "$(next_patch "$previous")")"
    fi
    [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
        || { echo "ERROR: version must look like 1.2.3, got '$version'" >&2; exit 1; }

    local notes_file
    notes_file="$(mktemp)"
    trap 'rm -f "$notes_file"' EXIT
    suggest_notes "$prev_tag" > "$notes_file"
    [[ -s "$notes_file" ]] || echo "- Maintenance release" > "$notes_file"
    echo
    echo "Release notes:"
    cat "$notes_file"
    local choice
    choice="$(ask "Use these notes? [Y]es / [e]dit / type a one-line note: " y)"
    case "$choice" in
        y|Y|yes) ;;
        e|E) "${EDITOR:-nano}" "$notes_file" ;;
        *) echo "$choice" > "$notes_file" ;;
    esac

    local deploy_worker=0
    if worker_changed "$prev_tag"; then
        deploy_worker=1
        command -v npx > /dev/null \
            || { echo "ERROR: the fleet Worker changed and npx is missing - install Node.js" >&2; exit 1; }
    fi

    echo
    echo "  release   $variant $version   (tag $variant-v$version)"
    echo "  worker    $([[ $deploy_worker -eq 1 ]] && echo "deploy - $WORKER_DIR changed since ${prev_tag:-the start}" || echo "unchanged, skipped")"
    echo "  pushes    main to GitHub and Codeberg"
    [[ "$(ask "Go ahead? [Y/n] " y)" =~ ^[Yy] ]] || { echo "Stopped - nothing published."; exit 1; }

    tools/make_release.sh "$variant" "$version" | sed '/^  variant /,$d'

    echo "==> Pushing main"
    git push -q origin main

    if [[ $deploy_worker -eq 1 ]]; then
        echo "==> Deploying the fleet Worker"
        (cd "$WORKER_DIR" && npx --yes wrangler deploy)
        if ! (cd "$WORKER_DIR" && npx --yes wrangler secret list 2> /dev/null) | grep -q ADMIN_PASSWORD; then
            echo "    the Worker has no ADMIN_PASSWORD yet - choose one now"
            (cd "$WORKER_DIR" && npx --yes wrangler secret put ADMIN_PASSWORD)
        fi
    fi

    echo "==> GitHub release"
    gh release create "$variant-v$version" \
        "dist/scheduler-$variant-$version.tar.gz" dist/version.json dist/SHA256SUMS \
        --title "$variant $version" --notes-file "$notes_file"

    echo "==> Codeberg"
    tools/mirror_codeberg.sh "$variant" "$version"

    echo
    echo "Published. Try it on one device first:"
    echo "  ssh <device> 'bash ~/Desktop/scheduler/config/scripts/check_updates.sh --target $version'"
    if [[ "$(ask "Roll out to every $variant device now? [y/N] " n)" =~ ^[Yy] ]]; then
        rollout "$variant" "$version"
    else
        echo "Later, roll out with:  tools/release.sh --rollout $variant $version"
    fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
